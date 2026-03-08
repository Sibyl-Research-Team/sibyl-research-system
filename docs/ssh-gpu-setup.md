# SSH & GPU Server Setup

Sibyl executes experiments on remote GPU servers via SSH. This guide covers the complete setup.

## SSH Configuration

### 1. SSH Key Access

Ensure you have SSH key access to your GPU server:

```bash
# Generate key if needed
ssh-keygen -t ed25519 -C "your-email@example.com"

# Copy public key to server
ssh-copy-id your-username@gpu-server-ip
```

### 2. SSH Config Entry

Add your GPU server to `~/.ssh/config`:

```
Host my-gpu-server
    HostName 192.168.1.100
    User your-username
    IdentityFile ~/.ssh/id_ed25519
    ServerAliveInterval 60
    ServerAliveCountMax 3
```

### 3. Verify Connection

```bash
ssh my-gpu-server "nvidia-smi"
```

### 4. Project Config

Set the SSH host name in your project `config.yaml`:

```yaml
ssh_server: "my-gpu-server"    # Must match Host in ~/.ssh/config
remote_base: "/home/your-username/sibyl_system"
max_gpus: 4
```

## Server-Side Directory Structure

Sibyl automatically creates this structure on the remote server:

```
{remote_base}/
├── projects/
│   └── <project-name>/        # Per-project experiment files
│       ├── code/              # Experiment scripts
│       ├── results/           # Output data
│       └── logs/              # Execution logs
├── shared/
│   ├── datasets/              # Shared datasets (cross-project)
│   ├── checkpoints/           # Shared model weights
│   └── registry.json          # Shared resource registry
└── miniconda3/                # Conda installation (if using conda)
    └── envs/
        └── sibyl_<project>/   # Per-project conda environment
```

To initialize this structure, use:

```bash
/sibyl-research:migrate-server <project>
```

## Python Environment on Server

### Option 1: Conda (Default)

```yaml
remote_env_type: "conda"
# remote_conda_path: ""  # Auto-detects {remote_base}/miniconda3/bin/conda
```

Create the conda environment on the server:

```bash
# On GPU server
conda create -n sibyl_<project> python=3.12 -y
conda activate sibyl_<project>
pip install torch transformers datasets matplotlib numpy scikit-learn
```

### Option 2: venv

```yaml
remote_env_type: "venv"
```

Create the venv on the server:

```bash
# On GPU server
cd /home/you/sibyl_system/projects/<project>
python3.12 -m venv .venv
source .venv/bin/activate
pip install torch transformers datasets matplotlib numpy scikit-learn
```

## GPU Configuration

### Dedicated Server

If you have exclusive GPU access:

```yaml
max_gpus: 8                    # Use all 8 GPUs
gpu_poll_enabled: false        # No need to poll
```

### Shared Server

If sharing GPUs with others:

```yaml
max_gpus: 4                    # Max GPUs to claim
gpu_poll_enabled: true         # Poll for free GPUs
gpu_free_threshold_mb: 2000    # GPU "free" if <2GB VRAM used
gpu_poll_interval_sec: 600     # Check every 10 minutes
gpu_poll_max_attempts: 0       # Wait indefinitely

# Aggressive mode: treat low-usage GPUs as available
gpu_aggressive_mode: true
gpu_aggressive_threshold_pct: 25  # <25% VRAM usage = available
```

### GPU Requirements

- CUDA-compatible NVIDIA GPU(s)
- NVIDIA driver with CUDA support
- `nvidia-smi` available in PATH
- Sufficient VRAM for your experiments (typically 16GB+ per GPU)

## Shared Resources

Sibyl supports shared datasets and model weights across projects to avoid redundant downloads.

The shared resource registry (`{remote_base}/shared/registry.json`) tracks downloaded resources. When an experiment needs a dataset or model weight:

1. Check `registry.json` for existing download
2. If found, create symlink to shared location
3. If not found, download and register for future use

## Troubleshooting

### SSH Connection Issues

```bash
# Test SSH connectivity
ssh -v my-gpu-server "echo OK"

# Check SSH MCP can see the server
# In Claude Code, use: mcp__ssh-mcp-server__list-servers
```

### GPU Not Detected

```bash
# Verify GPU visibility on server
ssh my-gpu-server "nvidia-smi"

# Check CUDA version
ssh my-gpu-server "nvcc --version"
```

### Permission Issues

Ensure your user has write access to `{remote_base}/`:

```bash
ssh my-gpu-server "mkdir -p /home/you/sibyl_system && ls -la /home/you/sibyl_system"
```
