# Optional qualification image, not the product's default or published runner.
# Supply the exact local prepared Fleet Python image ID and a digest-pinned
# official Node image. The current measured recipe is documented separately.
ARG FLEET_PYTHON_IMAGE
ARG NODE_IMAGE
FROM ${NODE_IMAGE} AS node_runtime
FROM ${FLEET_PYTHON_IMAGE}
COPY --from=node_runtime /usr/local/ /usr/local/
COPY --from=node_runtime /usr/lib/*-linux-gnu/libstdc++.so.6* /usr/lib/
COPY --from=node_runtime /usr/lib/*-linux-gnu/libgcc_s.so.1 /usr/lib/
