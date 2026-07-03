# SU-ERP API gateway image.
# Stock nginx (>=1.11 provides the $request_id variable used for X-Request-Id).
FROM nginx:1.27-alpine

# Replace the default config with our gateway config.
RUN rm -f /etc/nginx/conf.d/default.conf
COPY nginx.conf /etc/nginx/nginx.conf

# Validate the config at build time so a broken config fails the build.
RUN nginx -t

EXPOSE 8080

# Basic container healthcheck against the gateway liveness endpoint.
HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=5 \
    CMD wget -qO- http://127.0.0.1:8080/health || exit 1

CMD ["nginx", "-g", "daemon off;"]
