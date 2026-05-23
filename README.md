# RetroCheevos — Servidor

Plataforma alternativa ao RetroAchievements.org com compatibilidade total de protocolo (rcheevos).

## Pré-requisitos

- **Podman** 4+ (`podman --version`)
- **podman-compose** — o subcomando `podman compose` nativo requer docker-compose como provedor externo, que geralmente não está instalado. Instale via pip:

```bash
pip install --user podman-compose
# Ou, se precisar de sudo:
pip install podman-compose
```

## Setup inicial

```bash
# 1. Clonar o repositório
git clone ssh://git@codeberg.org/Gabriel-TwoBits/retrocheevos.git
cd retrocheevos

# 2. Copiar variáveis de ambiente
cp .env.example .env
# Edite .env se precisar de senhas diferentes em dev

# 3. Subir os serviços (constrói a imagem na primeira vez)
podman-compose up --build
```

O servidor estará disponível em http://localhost:8000

## Comandos comuns

```bash
# Aplicar migrations
podman-compose exec web python manage.py migrate

# Criar superusuário para o admin
podman-compose exec web python manage.py createsuperuser

# Abrir shell Django
podman-compose exec web python manage.py shell

# Rodar testes
podman-compose exec web python -m pytest

# Gerar lockfile após adicionar dependências em pyproject.toml
podman-compose exec web uv lock
# Depois: git add uv.lock && git commit

# Instalar nova dependência
podman-compose exec web uv add nome-do-pacote
# Depois: git add pyproject.toml uv.lock && git commit
```

## Acessar o admin

http://localhost:8000/admin/ → login com o superusuário criado acima.

## Subir em background

```bash
podman-compose up -d          # sobe em background
podman-compose logs -f web    # acompanha logs do servidor Django
podman-compose down           # derruba tudo (dados persistem nos volumes)
podman-compose down -v        # derruba E apaga os volumes (reset total)
```

## Primeira vez: gerar uv.lock

O lockfile `uv.lock` deve ser commitado no repositório para builds reproduzíveis.
Na primeira vez após o `podman-compose up --build`, gere-o assim:

```bash
podman-compose exec web uv lock
git add uv.lock
git commit -m "adiciona uv.lock inicial"
```

## Troubleshooting

### SELinux: permissão negada nos bind mounts

O Fedora usa SELinux em modo Enforcing. O `compose.yml` já adiciona `:Z` nos bind mounts,
o que relabela o diretório automaticamente. Se ainda ocorrer erro de permissão:

```bash
# Verificar contexto SELinux do diretório
ls -lZ .

# Relabelar manualmente se necessário
chcon -Rt svirt_sandbox_file_t .
```

### Ownership de arquivos criados pelo container

O container usa o usuário `app` com UID/GID 1000. No Fedora, o primeiro usuário
criado geralmente tem UID 1000, então os arquivos aparecem como seu usuário no host.

Se o seu UID for diferente de 1000, arquivos criados pelo container aparecerão como
UID 1000 no host. Soluções:

- Adicionar flag `:U` no bind mount do `compose.yml` (Podman remapeia UIDs automaticamente):
  ```yaml
  - ./:/app:Z,U
  ```
- Ou reconstruir a imagem com seu UID:
  ```bash
  # (requer ajuste no Containerfile para aceitar build arg UID)
  podman-compose build --build-arg UID=$(id -u)
  ```

### Porta 8000 já em uso

```bash
# Verificar o processo
ss -tlnp | grep 8000
# Mudar a porta no compose.yml: "8001:8000"
```

### Container `web` reiniciando em loop

```bash
# Ver logs completos
podman-compose logs web

# Problema comum: db ou redis ainda não prontos
# O compose já usa healthchecks, mas em hardware lento pode precisar de mais retries
```
