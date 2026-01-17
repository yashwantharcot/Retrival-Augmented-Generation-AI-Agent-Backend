"""Application package initializer.

This file also contains a small compatibility shim for pyarrow. Some
versions of the `datasets` / `sentence-transformers` stack attempt to
use `pyarrow.PyExtensionType`. Newer pyarrow exposes the same class as
`pyarrow.ExtensionType`. If `PyExtensionType` is missing, we alias it to
`ExtensionType` so imports don't fail at runtime.

This is a local, low-risk compatibility shim. For a long-term fix, pin
compatible versions of `pyarrow` and `datasets` in your environment.
"""

# Compatibility shim: alias PyExtensionType to ExtensionType if needed
try:
	import pyarrow as pa

	# Older/newer pyarrow naming mismatch: create alias only when safe
	if not hasattr(pa, "PyExtensionType") and hasattr(pa, "ExtensionType"):
		pa.PyExtensionType = pa.ExtensionType
except Exception:
	# If pyarrow isn't installed or anything goes wrong, skip silently.
	# The rest of the application will surface a clearer ImportError later.
	pass

# Compatibility shim for PyTorch's torch.compiler API
# Some older torch versions don't expose `torch.compiler` or the
# `disable` decorator used by `transformers`. Create a safe no-op
# decorator when missing so imports that reference
# `@torch.compiler.disable` won't fail at import time.
try:
	import torch

	if not hasattr(torch, "compiler"):
		class _DummyCompiler:
			@staticmethod
			def disable(*args, **kwargs):
				def _decorator(fn):
					return fn
				return _decorator

		torch.compiler = _DummyCompiler()
	else:
		# Ensure disable exists and is callable; if not, provide a no-op
		if not hasattr(torch.compiler, "disable"):
			def _disable_noop(*args, **kwargs):
				def _decorator(fn):
					return fn
				return _decorator

			torch.compiler.disable = _disable_noop
except Exception:
	# If torch isn't installed or any error occurs, silently continue.
	# The actual ImportError will surface if code attempts to use torch.
	pass
