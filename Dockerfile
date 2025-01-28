FROM python:3.11-slim

# Set the working directory
WORKDIR /app

# Copy everything not listed in .dockerignore into the container
COPY start.sh requirements.txt rp_handler.py ./
RUN chmod +x start.sh

# Install the runpod package
RUN pip install --no-cache-dir -r requirements.txt \
    && rm -rf /var/lib/apt/lists/* \
    && rm requirements.txt


# Set the command to execute the handler
CMD ["/app/start.sh"]
