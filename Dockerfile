FROM timpietruskyblibla/runpod-worker-comfy:3.1.2-base

RUN apt-get update && apt-get install -y \
    bash \
    openssh-server \
    && rm -rf /var/lib/apt/lists/*


# Add ssh key
RUN mkdir -p /root/.ssh
RUN chmod 700 /root/.ssh
COPY id_rsa.pub /root/.ssh/authorized_keys
RUN chmod 600 /root/.ssh/authorized_keys

COPY start.sh /
RUN chmod +x /start.sh

CMD ["/start.sh"]