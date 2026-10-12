# Install the Python package and its runtime dependencies.
FROM python:3.12-slim AS runtime

WORKDIR /app

COPY . .
RUN python -m pip install --no-cache-dir . \
    && useradd --uid 10001 --no-create-home --home-dir /nonexistent npc \
    && mkdir /population \
    && chown 10001:10001 /population

USER 10001:10001

# Mount saved Individual directories at /population. Override the arguments
# when using a different path, selection algorithm, score, or listen address.
VOLUME ["/population"]
EXPOSE 50051

# Forward container stop signal as a keyboard interrupt so the service can shut down cleanly.
STOPSIGNAL SIGINT

ENTRYPOINT ["npc-player"]
CMD ["/population", "random", "--listen", "0.0.0.0:50051"]
