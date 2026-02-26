# ─── Base image: Ubuntu 22.04 ────────────────────────────────────────────────
FROM ubuntu:22.04

# Avoid interactive prompts during package installation
ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=Asia/Kolkata
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

# ─── System dependencies ──────────────────────────────────────────────────────
RUN apt-get update && apt-get install -y \
    software-properties-common \
    git \
    wget \
    curl \
    unzip \
    xz-utils \
    libcairo2-dev \
    libpango1.0-dev \
    libjpeg-dev \
    libpng-dev \
    gcc \
    g++ \
    make \
    cmake \
    ffmpeg \
    texlive \
    texlive-latex-extra \
    texlive-fonts-extra \
    texlive-latex-recommended \
    texlive-science \
    texlive-fonts-recommended \
    dvipng \
    dvisvgm \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# ─── Add deadsnakes PPA for Python 3.13 ───────────────────────────────────────
RUN add-apt-repository ppa:deadsnakes/ppa -y \
    && apt-get update \
    && apt-get install -y \
    python3.13 \
    python3.13-dev \
    python3.13-venv \
    python3-pip \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# ─── Python virtual environment (Python 3.13) ─────────────────────────────────
ENV VIRTUAL_ENV=/opt/venv
RUN python3.13 -m venv $VIRTUAL_ENV
ENV PATH="$VIRTUAL_ENV/bin:$PATH"
RUN pip install --upgrade pip setuptools wheel

# ─── PyTorch with CUDA 11.8 ──────────────────────────────────────────────────
RUN pip install --no-cache-dir \
    torch==2.7.1+cu118 \
    torchvision==0.22.1+cu118 \
    torchaudio==2.7.1+cu118 \
    --index-url https://download.pytorch.org/whl/cu118

# ─── Python dependencies from requirements.txt (filtered) ─────────────────────
COPY requirements.txt /tmp/requirements.txt

RUN grep -v "^torch==" /tmp/requirements.txt \
    | grep -v "^torchvision==" \
    | grep -v "^torchaudio==" \
    | grep -v "^pyobjc" \
    | grep -v "^opencv-python==" \
    | grep -v "^transformers" \
    | grep -v "^paddleocr" \
    | grep -v "^paddlepaddle" \
    | grep -v "^paddlex" \
    > /tmp/requirements_linux.txt \
    && pip install --no-cache-dir -r /tmp/requirements_linux.txt

# ─── Transformers from specific git commit ────────────────────────────────────
RUN pip install --no-cache-dir \
    "transformers @ git+https://github.com/huggingface/transformers@24807bfcf4a21286fa2a7e728f381ddaaca7bbc7"

# ─── Gunicorn + HuggingFace Hub ──────────────────────────────────────────────
RUN pip install --no-cache-dir gunicorn==23.0.0 huggingface_hub

# ─── Application code ─────────────────────────────────────────────────────────
WORKDIR /app
COPY . .

# ─── Environment variables ────────────────────────────────────────────────────
ENV MANIM_BIN=/opt/venv/bin/manim
ENV PYTHON_BIN=/opt/venv/bin/python
ENV SAM3_MODEL_PATH=/app/models/sam3
ENV YOLO_MODEL_PATH=/app/models/player/circle_square.pt
ENV YOLO_ALPHABET_MODEL_PATH=/app/models/player/alphabets.pt
ENV PYTHONUNBUFFERED=1

# ─── Output directories ───────────────────────────────────────────────────────
RUN mkdir -p /app/manim_outputs \
             /app/audio_output/male \
             /app/media/videos

# ─── Download models from HuggingFace Dataset repo ───────────────────────────
RUN python3.13 -c "\
import os; \
from huggingface_hub import snapshot_download; \
snapshot_download( \
    repo_id='prathmeshg/playbook-models', \
    repo_type='dataset', \
    local_dir='/app/models', \
    token=os.environ.get('HF_TOKEN') \
)"

# ─── Expose and run ──────────────────────────────────────────────────────────
EXPOSE 5050
CMD ["gunicorn", \
     "--bind", "0.0.0.0:5050", \
     "--workers", "2", \
     "--timeout", "3600", \
     "--keep-alive", "5", \
     "--access-logfile", "-", \
     "server:app"]