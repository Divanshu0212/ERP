# SU-ERP API gateway image.
# Stock nginx (>=1.11 provides the $request_id variable used for X-Request-Id).
FROM nginx:1.27-alpine

# Replace the default config with our gateway config.
RUN rm -f /etc/nginx/conf.d/default.conf
COPY nginx.conf /etc/nginx/nginx.conf

# NOTE: `nginx -t` is intentionally NOT run at build time — it resolves the
# upstream hostnames (auth-service, etc.) via DNS, which do not exist during
# an isolated image build and would fail the build. nginx still parses and
# resolves upstreams when the container starts on the shared suerp-net network.

EXPOSE 8080

# Basic container healthcheck against the gateway liveness endpoint.
HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=5 \
    CMD wget -qO- http://127.0.0.1:8080/health || exit 1

CMD ["nginx", "-g", "daemon off;"]
