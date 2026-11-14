# Marketing website and BOXGPT on one domain

This layout keeps the two applications separate while publishing both through
`demo.boxgpt.online`:

- `/`, `/banking`, and `/manufacturing` are static files from `marketing-site/`.
- `/login`, `/app`, `/static/`, and an explicit allowlist of `/api/` routes are
  served by FastAPI on `127.0.0.1:8000`.
- `/health`, API documentation, the OpenAPI schema, and unknown API routes are
  not publicly exposed by Nginx. Health checks remain available locally at
  `http://127.0.0.1:8000/health` on the EC2 instance.

## Deploy on EC2

From `/home/ubuntu/boxgptcode`:

```bash
sudo mkdir -p /var/www/boxgpt-site
sudo rsync -a --delete marketing-site/ /var/www/boxgpt-site/
sudo chown -R www-data:www-data /var/www/boxgpt-site

sudo cp deploy/nginx/boxgpt.conf /etc/nginx/sites-available/boxgpt
sudo ln -sfn /etc/nginx/sites-available/boxgpt /etc/nginx/sites-enabled/boxgpt
sudo rm -f /etc/nginx/sites-enabled/default

sudo nginx -t
sudo systemctl reload nginx
```

Test before changing DNS:

```bash
curl -s -o /dev/null -w "%{http_code}\n" \
  -H "Host: demo.boxgpt.online" http://127.0.0.1/

curl -s -o /dev/null -w "%{http_code}\n" \
  -H "Host: demo.boxgpt.online" http://127.0.0.1/login
```

Both commands should print `200`.

Point the `demo.boxgpt.online` DNS A record to the BOXGPT EC2 Elastic IP. Once
DNS resolves to the new server, install or renew the TLS certificate and set
`COOKIE_SECURE=true` in `.env.web`.

The website's **Sign in** links use `/login`, so the browser stays on the same
domain and Nginx passes the request to BOXGPT.
