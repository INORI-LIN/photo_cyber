"""GPU benchmark for SD perturber — one-off script, not committed."""
import time, sys, numpy as np, os
from PIL import Image
from pathlib import Path

tmpdir = Path(os.environ.get('TEMP', '.')) / 'pg_gpu_test'
tmpdir.mkdir(parents=True, exist_ok=True)
img_path = tmpdir / 'in.jpg'
out_path = tmpdir / 'out.jpg'

# Create test image
img = Image.new('RGB', (512, 512), (128, 128, 128))
img.save(img_path, quality=95)

from photo_guard.pipeline import protect, ProtectOptions
perturb_only = frozenset({'perturb'})

print("=" * 50)
print("photo-guard GPU Benchmark")
print("=" * 50)

# 1. noop baseline
t0 = time.perf_counter()
opts = ProtectOptions(perturber='noop', layers=perturb_only)
protect(img_path, out_path, opts)
print(f'noop (baseline):       {time.perf_counter() - t0:.4f}s')

# 2. noise
t0 = time.perf_counter()
opts = ProtectOptions(perturber='noise',
                      perturber_kwargs={'epsilon': 2.0/255},
                      layers=perturb_only)
protect(img_path, out_path, opts)
print(f'noise (e=2/255):       {time.perf_counter() - t0:.4f}s')

# 3. Check device
import torch
dev = torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CPU'
print(f'Device: {dev}')

# 4. SD 10 steps at 512px
t0 = time.perf_counter()
opts = ProtectOptions(
    perturber='sd',
    perturber_kwargs={'epsilon': 8.0/255, 'step_size': 2.0/255, 'steps': 10},
    layers=perturb_only
)
protect(img_path, out_path, opts)
print(f'sd-512px-10steps:      {time.perf_counter() - t0:.3f}s')

# 5. SD 20 steps at 512px
t0 = time.perf_counter()
opts = ProtectOptions(
    perturber='sd',
    perturber_kwargs={'epsilon': 8.0/255, 'step_size': 2.0/255, 'steps': 20},
    layers=perturb_only
)
protect(img_path, out_path, opts)
print(f'sd-512px-20steps:      {time.perf_counter() - t0:.3f}s')

# 6. Different resolutions (10 steps)
for size, name in [(256, '256px'), (512, '512px'), (1024, '1024px')]:
    test_img = Image.new('RGB', (size, size), (128, 128, 128))
    test_img.save(img_path, quality=95)
    t0 = time.perf_counter()
    opts = ProtectOptions(
        perturber='sd',
        perturber_kwargs={'epsilon': 8.0/255, 'step_size': 2.0/255, 'steps': 10},
        layers=perturb_only,
        long_edge=max(size * 2, 1080)
    )
    protect(img_path, out_path, opts)
    print(f'sd-{name}-10steps:      {time.perf_counter() - t0:.3f}s')

# 7. Verify perturbation bounds
in_arr = np.array(Image.open(img_path))
out_arr = np.array(Image.open(out_path))
diff = np.abs(in_arr.astype(float) - out_arr.astype(float))
print(f'\nPerturbation L-inf: {diff.max()/255:.4f} (budget={8/255:.4f})')
print(f'Perturbation mean:  {diff.mean():.2f} / 255')

import shutil
shutil.rmtree(tmpdir)
print('\nDone.')
