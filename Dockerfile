
ARG MY_BASE_IMAGE

# A comfy worker image we get Python dependencies from
FROM timpietruskyblibla/runpod-worker-comfy:3.1.2-base AS comfy-base

FROM ${MY_BASE_IMAGE} AS final

ARG IMAGE_TYPE
ENV DOCKER_IMAGE_TYPE=${IMAGE_TYPE}

# apt -y install ffmpeg is failing, so install this way
RUN apt-get update || true && \
apt-get install -y --no-install-recommends gnupg wget xz-utils && \
apt-key adv --fetch-keys http://archive.ubuntu.com/ubuntu/ubuntu-keyring.gpg && \
apt-get clean && \
rm -rf /var/lib/apt/lists/* && \
wget https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz && \
tar -xf ffmpeg-release-amd64-static.tar.xz && \
cd ffmpeg-*-amd64-static && \
mv ffmpeg ffprobe /usr/local/bin/ && \
cd .. && rm -rf ffmpeg-*-amd64-static ffmpeg-release-amd64-static.tar.xz

COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt; \
    rm -f requirements.txt

# Modified files from the comfy-base image
COPY start.sh rp_handler.py /
RUN chmod +x /start.sh

CMD ["/start.sh"]