# GLTD Notes — Bloco de Notas Pessoal com Sincronização Multi-Máquina

## O que é o GLTD Notes?

Um aplicativo de notas **privado e de código aberto** para Linux, feito como alternativa ao GNote. Ele oferece interface gráfica desktop (GTK 3), servidor web local e API REST — tudo rodando na sua máquina, sem depender de nuvem ou servidor externo.

### Por que ele existe?

- **Privacidade real**: todos os dados ficam no seu computador, na sua pasta.
- **Sincronização entre máquinas**: use o **Syncthing** para manter suas notas sincronizadas entre vários computadores sem servidor central. O formato de armazenamento evita conflitos quando duas pessoas editam ao mesmo tempo.
- **Histórico completo**: cada alteração fica registrada. Você pode voltar a qualquer versão anterior de uma nota.
- **Agentes de IA integrados**: descreva tarefas em linguagem natural e peça para o DeepSeek (via opencode), Grok ou Gemini executarem automaticamente.

> **Este aplicativo foi desenvolvido com auxílio de inteligência artificial usando Grok (xAI) e DeepSeek V4 (via opencode).**

---

## Como instalar

### 1. Dependências do sistema

Execute o comando abaixo no terminal (Linux Mint / Ubuntu / Debian):

```bash
sudo apt install python3 python3-gi python3-gi-cairo \
  gir1.2-gtk-3.0 gir1.2-notify-0.7 \
  gir1.2-ayatanaappindicator3-0.1 libnotify-bin
```

### 2. Localização dos arquivos

O programa já está instalado em:

```
/var/PROGRAMAS/gltd_notes/          ← código do aplicativo
~/gltd_notes_data/                ← seus dados (notas, anexos, histórico)
~/.config/gltd_notes/config.json    ← configuração local e senhas
~/.local/share/gltd_notes/session/  ← controle de sessão bloqueada
```

### 3. Inicialização (primeiro uso)

Antes de abrir o programa, crie seu usuário e defina a senha:

```bash
/var/PROGRAMAS/gltd_notes/bin/gltd-notes init \
  --data-root ~/gltd_notes_data \
  --username SEU_USUARIO --password 'SUA_SENHA'
```

### 4. Criar atalhos no menu do sistema (opcional)

```bash
/var/PROGRAMAS/gltd_notes/scripts/install_desktop.sh
```

Isso adiciona entradas no menu do sistema e links em `~/.local/bin/` para os comandos `gltd-notes`, `gltd-notes-api` e `gltd-notes-web`.

---

## Como usar

### Interface gráfica (modo normal)

```bash
gltd-notes gui
```

- Crie, edite e delete notas com formatação de texto.
- Anexe arquivos (imagens, PDFs, qualquer coisa) — cada arquivo é armazenado por conteúdo, evitando duplicatas.
- Veja o **histórico** de alterações e restaure versões anteriores.
- Crie **eventos/lembretes** que disparam notificações na área de trabalho.
- Use o **ícone na bandeja do sistema** (tray) para acesso rápido: nova nota, novo evento, mostrar janela, sair.
- **Bloqueie a sessão** com senha — enquanto bloqueada, ninguém acessa as notas.

### Interface web

```bash
gltd-notes web
```

Abra o navegador em `http://127.0.0.1:8765` para acessar as notas pela web.

### API REST

```bash
gltd-notes api
```

A API REST fica disponível em `http://127.0.0.1:8765` (apenas localhost). Todas as requisições precisam do header:

```
X-API-Key: <chave em ~/.config/gltd_notes/config.json>
```

Exemplos:

```bash
# Obter a chave da API
KEY=$(python3 -c "import json;print(json.load(open('$HOME/.config/gltd_notes/config.json'))['api']['api_key'])")

# Verificar se está funcionando
curl -s -H "X-API-Key: $KEY" http://127.0.0.1:8765/api/v1/health

# Criar uma nota
curl -s -H "X-API-Key: $KEY" -H 'Content-Type: application/json' \
  -d '{"title":"Minha nota","body":"Conteúdo da nota via API"}' \
  http://127.0.0.1:8765/api/v1/notes

# Listar todas as notas
curl -s -H "X-API-Key: $KEY" http://127.0.0.1:8765/api/v1/notes
```

---

## Tarefas com Agentes de IA

O GLTD Notes permite delegar tarefas para agentes de IA. Você escreve o que precisa fazer e o agente executa no terminal.

### Agentes disponíveis

| Nome na interface | Ferramenta CLI | O que faz |
|-------------------|----------------|-----------|
| `opencode-deepseek4` | `opencode run` | Executa tarefas usando DeepSeek V4 |
| `grok` | `grok` | Executa tarefas usando Grok |
| `gemini` | `gemini` | Executa tarefas usando Gemini |

### Como usar

1. No menu, vá em **Tarefas → Nova tarefa para agente**.
2. Escolha o agente (recomendado: `opencode-deepseek4`).
3. Descreva a tarefa em linguagem natural. Seja específico.
4. Clique **▶ Executar** e aguarde o resultado no campo de output.

### Exemplo de tarefa

```
Configurar o servidor 192.0.2.1:
1. Acessar via SSH como root
2. Instalar e configurar o MariaDB
3. Criar banco de dados "app_producao"
4. Criar usuário "app_user" com senha segura
5. Configurar backup diário com cron
```

Para mais detalhes sobre agentes, veja [README_AGENT.md](README_AGENT.md).

---

## Sincronização entre máquinas com Syncthing

1. Instale o [Syncthing](https://syncthing.net/) em todas as máquinas.
2. Em cada máquina, compartilhe a pasta de dados do GLTD Notes (`~/gltd_notes_data`).
3. Pronto. As notas sincronizam automaticamente.

**Por que não dá conflito?** O programa usa um formato especial chamado "blockchain de notas": cada alteração é um bloco novo adicionado ao final do arquivo, com identificação de máquina e usuário. Quando duas pessoas editam a mesma nota ao mesmo tempo, as duas versões são preservadas e podem ser visualizadas no histórico.

---

## Compartilhamento de notas

No GLTD Notes você pode compartilhar notas com outros usuários:

- Notas privadas: visíveis apenas para você.
- Notas compartilhadas: copiadas para a área `shared/` e visíveis para todos os usuários listados.
- O histórico mostra qual usuário e qual máquina produziu cada alteração.

---

## Documentação

| Arquivo | Conteúdo |
|---------|----------|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Armazenamento, blockchain e sincronização multi-máquina |
| [docs/API.md](docs/API.md) | Referência completa da API REST |
| [docs/SECURITY.md](docs/SECURITY.md) | Modelo de autenticação e segurança |
| [docs/PACKAGING.md](docs/PACKAGING.md) | Planos futuros (.deb, AppImage, etc.) |
| [README_AGENT.md](README_AGENT.md) | Guia detalhado das tarefas com agentes de IA |

---

## Versionamento

O numero de versao segue o formato `MAJOR.MINOR.PATCH` (versionamento semantico):

- **MAJOR**: mudancas incompativeis de API ou reescritas completas (atualmente `0` — pre-estavel)
- **MINOR**: novas funcionalidades, novos subcomandos, novas paginas da interface (`1`)
- **PATCH**: correcoes de bugs, pequenas melhorias, atualizacoes de documentacao — **incrementado automaticamente a cada commit**

O numero de patch e gerenciado automaticamente pelo `.githooks/pre-commit`, que executa `scripts/bump_version.sh` antes de cada commit. A fonte canonica da versao e `gltd_notes/_version.py` — todas as outras referencias (`pyproject.toml`, endpoints de health da API, `__init__.py`) derivam dela.

---

## Doações

Se o GLTD Notes for util para voce, considere apoiar o desenvolvimento:

- **Pix (Brasil)**: `1f57a276-dc0e-44a0-a4e0-4a2349833958`
- **Monero (XMR)**: `84pnTEwRrFLPUqSNQdCLFw6X6gjQeQtdNNVxkYAfvgd229DHgNYzzQ9VgpquUG8RfAJJ5Py556KrAiG47PqKYxPM1mzpAtb`

---

## Sobre o desenvolvimento

Este aplicativo foi desenvolvido com auxílio de **inteligência artificial** utilizando:

- **Grok** (xAI) — prototipagem e iterações iniciais
- **DeepSeek V4** via opencode — arquitetura final, refinamento e completude

O código é 100% aberto (licença MIT). Consulte o arquivo [LICENSE](LICENSE).
