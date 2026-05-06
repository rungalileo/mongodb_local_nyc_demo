# AI Operations Desk - Multi-Agent Demo

# Patch Galileo SDK bug: is_content_block_list([]) incorrectly returns True
# for empty lists, causing tool span output validation to fail. Applied here
# so it takes effect for both CLI and API entry points.
import galileo.schema.content_blocks as _cb
import galileo.decorator as _gd

_orig_is_content_block_list = _cb.is_content_block_list
_fixed = lambda v: bool(v) and _orig_is_content_block_list(v)
_cb.is_content_block_list = _fixed
_gd.is_content_block_list = _fixed
