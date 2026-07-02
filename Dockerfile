# Ubuntu 22.04 + CUDA runtime so Docling's torch models can use the GPU.
# Mirrors the noted graph service base. Requires the NVIDIA container toolkit
# on the host and a matching driver.
FROM nvidia/cuda:12.4.1-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src

# Python 3.12 via deadsnakes (Ubuntu 22.04 default is 3.10).
# The libgl / libglib / libx* set is required by Docling's layout/image stack.
RUN apt-get update && apt-get install -y --no-install-recommends \
      software-properties-common ca-certificates curl gnupg \
 && add-apt-repository -y ppa:deadsnakes/ppa \
 && apt-get update && apt-get install -y --no-install-recommends \
      python3.12 python3.12-venv python3.12-dev \
      build-essential \
      libgl1 libglib2.0-0 libxcb1 libxext6 libxrender1 libsm6 \
 && rm -rf /var/lib/apt/lists/* \
 && update-alternatives --install /usr/bin/python python /usr/bin/python3.12 1 \
 && update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.12 1

# Python 3.12-native pip (Ubuntu's python3-pip binds to 3.10).
RUN python3.12 -m ensurepip --upgrade \
 && python3.12 -m pip install --no-cache-dir --upgrade 'pip>=24.0' 'setuptools>=68' wheel

WORKDIR /app

COPY requirements.txt .
RUN python3.12 -m pip install --no-cache-dir -r requirements.txt

# Docling's layout + TableFormer models, pre-downloaded on the host into
# ./models/docling (see README / `download_models`). Copied in at build time so
# the build is offline and reproducible — no HuggingFace fetch during build.
ENV DOCLING_ARTIFACTS_PATH=/opt/docling-models
COPY models/docling /opt/docling-models

COPY src/ src/

EXPOSE 5601

CMD ["python3.12", "-m", "uvicorn", "reqqa.api:app", "--host", "0.0.0.0", "--port", "5601"]
