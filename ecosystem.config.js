// PM2 process manager konfigürasyonu — 99-root Kişisel AI Ajan
// Kullanım: pm2 start ecosystem.config.js
// Bkz: docs/deployment/byok.md — alternatif kurulum seçenekleri
module.exports = {
  apps: [
    {
      name: "99-api",
      script: "backend/venv/bin/uvicorn",
      args: "backend.main:app --host 0.0.0.0 --port 8010",
      cwd: "./scripts",
      env_file: "./scripts/backend/.env",
      restart_delay: 3000,
      max_restarts: 10,
      watch: false,
    },
    {
      name: "99-bridge",
      script: "node",
      args: "server.js",
      cwd: "./scripts/claude-code-bridge",
      env_file: "./scripts/backend/.env",
      restart_delay: 3000,
      max_restarts: 10,
      watch: false,
    },
  ],
};
