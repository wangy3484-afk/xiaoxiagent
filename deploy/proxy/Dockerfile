FROM nginxinc/nginx-unprivileged:1.29-alpine@sha256:0c79d56aee561a1d81c63f00eee5fb5fe29279560cdc55e91425133104c7fbe6

COPY nginx.conf /etc/nginx/conf.d/default.conf

USER 101:101

EXPOSE 8080 8443

HEALTHCHECK --interval=10s --timeout=5s --start-period=5s --retries=12 \
    CMD wget --spider --quiet http://127.0.0.1:8080/proxy-healthz || exit 1

CMD ["nginx", "-g", "daemon off;"]
