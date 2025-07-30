import logging
from importlib import resources
from typing import TYPE_CHECKING
from urllib.parse import urlparse

if TYPE_CHECKING:
	from browser_use.browser.types import Page


from browser_use.dom.cache import get_dom_cache
from browser_use.dom.views import (
	DOMBaseNode,
	DOMElementNode,
	DOMState,
	DOMTextNode,
	SelectorMap,
	ViewportInfo,
)
from browser_use.observability import observe_debug
from browser_use.utils import is_new_tab_page, time_execution_async

# @dataclass
# class ViewportInfo:
# 	width: int
# 	height: int


class DomService:
	"""
	PYTHON DOM SERVICE - ORCHESTRATOR
	=================================
	This service coordinates DOM extraction between browser and Python.
	
	WORKFLOW:
	STEP 7: Python receives request for DOM state
	STEP 8: Check cache for recent DOM state
	STEP 9: Execute JavaScript DOM extraction
	STEP 10: Convert JavaScript results to Python objects
	STEP 11: Cache and return DOM state
	"""
	logger: logging.Logger

	def __init__(self, page: 'Page', logger: logging.Logger | None = None):
		"""
		Initialize DOM service for a specific browser page.
		
		Components:
		- page: Playwright page instance
		- xpath_cache: Cache for XPath lookups (legacy)
		- dom_cache: Global DOM state cache (optimized)
		- js_code: JavaScript DOM extraction code (index.js)
		"""
		self.page = page
		self.xpath_cache = {}
		self.logger = logger or logging.getLogger(__name__)
		self.dom_cache = get_dom_cache()

		# Load JavaScript code once at initialization
		self.js_code = resources.files('browser_use.dom.dom_tree').joinpath('index.js').read_text()

	# region - Clickable elements
	@observe_debug(ignore_input=True, ignore_output=True, name='get_clickable_elements')
	@time_execution_async('--get_clickable_elements')
	async def get_clickable_elements(
		self,
		highlight_elements: bool = True,
		focus_element: int = -1,
		viewport_expansion: int = 0,
	) -> DOMState:
		"""
		STEP 7: Main entry point for DOM extraction
		===========================================
		This is called by the agent when it needs to understand the page.
		
		Parameters:
		- highlight_elements: Whether to create visual highlights
		- focus_element: Specific element index to focus on (-1 for none)
		- viewport_expansion: Pixels to expand viewport for detection
		
		Returns:
		- DOMState containing element tree and selector map
		"""
		
		# STEP 8: Check cache for recent DOM state
		# ========================================
		# Cache key is based on: page URL + parameters
		# TTL is 2 seconds by default
		cached_state = await self.dom_cache.get(
			self.page, highlight_elements, focus_element, viewport_expansion
		)
		if cached_state:
			self.logger.debug("DOM cache hit - returning cached state")
			return cached_state
		
		# STEP 9: Build DOM tree if not cached
		# ====================================
		# This will execute JavaScript in the browser
		element_tree, selector_map = await self._build_dom_tree(highlight_elements, focus_element, viewport_expansion)
		dom_state = DOMState(element_tree=element_tree, selector_map=selector_map)
		
		# STEP 11: Cache the result for future requests
		# =============================================
		await self.dom_cache.set(
			self.page, highlight_elements, focus_element, viewport_expansion, dom_state
		)
		
		return dom_state

	@time_execution_async('--get_cross_origin_iframes')
	async def get_cross_origin_iframes(self) -> list[str]:
		# invisible cross-origin iframes are used for ads and tracking, dont open those
		hidden_frame_urls = await self.page.locator('iframe').filter(visible=False).evaluate_all('e => e.map(e => e.src)')

		is_ad_url = lambda url: any(
			domain in urlparse(url).netloc for domain in ('doubleclick.net', 'adroll.com', 'googletagmanager.com')
		)

		return [
			frame.url
			for frame in self.page.frames
			if urlparse(frame.url).netloc  # exclude data:urls and new tab pages
			and urlparse(frame.url).netloc != urlparse(self.page.url).netloc  # exclude same-origin iframes
			and frame.url not in hidden_frame_urls  # exclude hidden frames
			and not is_ad_url(frame.url)  # exclude most common ad network tracker frame URLs
		]

	@time_execution_async('--build_dom_tree')
	async def _build_dom_tree(
		self,
		highlight_elements: bool,
		focus_element: int,
		viewport_expansion: int,
	) -> tuple[DOMElementNode, SelectorMap]:
		"""
		STEP 9: Execute JavaScript DOM extraction
		=========================================
		This is where we inject and run our JavaScript code in the browser.
		
		WORKFLOW:
		9.1: Verify JavaScript execution capability
		9.2: Handle special cases (empty tabs, chrome:// pages)
		9.3: Prepare arguments for JavaScript
		9.4: Execute index.js in browser context
		9.5: Process returned data
		"""
		
		# 9.1: Sanity check - ensure JavaScript can execute
		if await self.page.evaluate('1+1') != 2:
			raise ValueError('The page cannot evaluate javascript code properly')

		# 9.2: Optimize for empty/system pages
		if is_new_tab_page(self.page.url) or self.page.url.startswith('chrome://'):
			# Return empty DOM structure without JavaScript execution
			return (
				DOMElementNode(
					tag_name='body',
					xpath='',
					attributes={},
					children=[],
					is_visible=False,
					parent=None,
				),
				{},
			)

		# 9.3: Prepare arguments for JavaScript execution
		# These args are passed to the main function in index.js
		debug_mode = self.logger.getEffectiveLevel() == logging.DEBUG
		args = {
			'doHighlightElements': highlight_elements,      # Create visual overlays
			'focusHighlightIndex': focus_element,           # Specific element to focus
			'viewportExpansion': viewport_expansion,         # Viewport detection margin
			'debugMode': debug_mode,                         # Enable performance metrics
		}

		# 9.4: Execute JavaScript DOM extraction
		# This runs our entire index.js code in the browser
		try:
			self.logger.debug(f'🔧 Starting JavaScript DOM analysis for {self.page.url[:50]}...')
			eval_page: dict = await self.page.evaluate(self.js_code, args)
			self.logger.debug('✅ JavaScript DOM analysis completed')
		except Exception as e:
			self.logger.error('Error evaluating JavaScript: %s', e)
			raise

		# Only log performance metrics in debug mode
		if debug_mode and 'perfMetrics' in eval_page:
			perf = eval_page['perfMetrics']

			# Get key metrics for summary
			total_nodes = perf.get('nodeMetrics', {}).get('totalNodes', 0)
			# processed_nodes = perf.get('nodeMetrics', {}).get('processedNodes', 0)

			# Count interactive elements from the DOM map
			interactive_count = 0
			if 'map' in eval_page:
				for node_data in eval_page['map'].values():
					if isinstance(node_data, dict) and node_data.get('isInteractive'):
						interactive_count += 1

			# Create concise summary
			url_short = self.page.url[:50] + '...' if len(self.page.url) > 50 else self.page.url
			self.logger.debug(
				'🔎 Ran buildDOMTree.js interactive element detection on: %s interactive=%d/%d\n',
				url_short,
				interactive_count,
				total_nodes,
				# processed_nodes,
			)

		# 9.5: Convert JavaScript results to Python objects
		self.logger.debug('🔄 Starting Python DOM tree construction...')
		result = await self._construct_dom_tree(eval_page)
		self.logger.debug('✅ Python DOM tree construction completed')
		return result

	@time_execution_async('--construct_dom_tree')
	async def _construct_dom_tree(
		self,
		eval_page: dict,
	) -> tuple[DOMElementNode, SelectorMap]:
		"""
		STEP 10: Convert JavaScript results to Python objects
		====================================================
		Transform the JavaScript hash map into Python DOM tree structure.
		
		WORKFLOW:
		10.1: Extract data from JavaScript response
		10.2: Parse each node into Python objects
		10.3: Build parent-child relationships
		10.4: Create selector map for quick lookups
		10.5: Return complete DOM tree
		
		Data structure from JavaScript:
		- eval_page['map']: Hash map of all DOM nodes
		- eval_page['rootId']: ID of root element (body)
		"""
		
		# 10.1: Extract JavaScript data structures
		js_node_map = eval_page['map']      # All DOM nodes by ID
		js_root_id = eval_page['rootId']    # Root node ID

		# 10.2: Initialize Python data structures
		selector_map = {}    # Maps highlight_index -> DOMElementNode
		node_map = {}        # Maps node_id -> DOMNode

		# 10.3: First pass - create all nodes
		for id, node_data in js_node_map.items():
			# Parse JavaScript node data into Python objects
			node, children_ids = self._parse_node(node_data)
			if node is None:
				continue

			# Store node in map
			node_map[id] = node

			# 10.4: Build selector map for interactive elements
			# This allows quick lookup by highlight index
			if isinstance(node, DOMElementNode) and node.highlight_index is not None:
				selector_map[node.highlight_index] = node

		# 10.5: Second pass - build tree relationships
		# We process bottom-up, so children are already created
		for id, node_data in js_node_map.items():
			if id not in node_map:
				continue
				
			node = node_map[id]
			if isinstance(node, DOMElementNode):
				# Get children IDs from original data
				_, children_ids = self._parse_node(node_data)
				
				# Link children to parent
				for child_id in children_ids:
					if child_id not in node_map:
						continue

					child_node = node_map[child_id]
					child_node.parent = node
					node.children.append(child_node)

		# 10.6: Get root element
		html_to_dict = node_map[str(js_root_id)]

		del node_map
		del js_node_map
		del js_root_id

		if html_to_dict is None or not isinstance(html_to_dict, DOMElementNode):
			raise ValueError('Failed to parse HTML to dictionary')

		return html_to_dict, selector_map

	def _parse_node(
		self,
		node_data: dict,
	) -> tuple[DOMBaseNode | None, list[int]]:
		if not node_data:
			return None, []

		# Process text nodes immediately
		if node_data.get('type') == 'TEXT_NODE':
			text_node = DOMTextNode(
				text=node_data['text'],
				is_visible=node_data['isVisible'],
				parent=None,
			)
			return text_node, []

		# Process coordinates if they exist for element nodes

		viewport_info = None

		if 'viewport' in node_data:
			viewport_info = ViewportInfo(
				width=node_data['viewport']['width'],
				height=node_data['viewport']['height'],
			)

		element_node = DOMElementNode(
			tag_name=node_data['tagName'],
			xpath=node_data['xpath'],
			attributes=node_data.get('attributes', {}),
			children=[],
			is_visible=node_data.get('isVisible', False),
			is_interactive=node_data.get('isInteractive', False),
			is_top_element=node_data.get('isTopElement', False),
			is_in_viewport=node_data.get('isInViewport', False),
			highlight_index=node_data.get('highlightIndex'),
			shadow_root=node_data.get('shadowRoot', False),
			parent=None,
			viewport_info=viewport_info,
		)

		children_ids = node_data.get('children', [])

		return element_node, children_ids
