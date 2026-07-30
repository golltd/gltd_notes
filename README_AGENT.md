# GLTD Notes — Tarefas com Agentes de IA

> Guia otimizado para **DeepSeek** via [opencode](https://github.com/anomalyco/opencode).
> Compatível também com grok (xAI) e gemini (Google).

## Visão geral

O GLTD Notes permite **descrever tarefas em linguagem natural** e executá-las
automaticamente por agentes CLI instalados localmente. Cada tarefa de agente
é armazenada como uma nota especial (`kind: agent_task`) com campos
`description` (entrada) e `output` (resultado).

### Agentes suportados

| Label na UI         | CLI              | Modo headless              |
|---------------------|------------------|----------------------------|
| `grok`              | `grok`           | `grok -p "prompt" --always-approve --output-format json` |
| `gemini`            | `gemini`         | `gemini -p "prompt"`       |
| `opencode-deepseek4`| `opencode`       | `opencode run --auto --pure "prompt"` |

> O nome `opencode-deepseek4` na UI é herdado — por baixo chama `opencode run`.

## Arquitetura

```
┌─ GUI (main_window.py) ─────────────────────────────────┐
│  AgentTaskEditor (agent_editor.py)                      │
│    input:  descrição da tarefa (TextView)               │
│    output: resultado do agente (TextView)               │
│    botão:  ▶ Play / Executar                            │
│        ↓                                                │
│  _play_agent_task() → thread → AgentTasksService        │
└─────────────────────────────────────────────────────────┘
                              ↓
┌─ services/agent_tasks.py ───────────────────────────────┐
│  resolve_agent_command(agent)                            │
│    1. env var GLTD_AGENT_*  (shell template)             │
│    2. named CLI auto-detect (grok/gemini/opencode)       │
│    3. ollama fallback (local models)                     │
│        ↓                                                 │
│  subprocess.run(cmd, ...) → stdout/stderr → output       │
└──────────────────────────────────────────────────────────┘
```

## Prioridade de resolução

A função `resolve_agent_command()` escolhe o executor nesta ordem:

1. **Variáveis de ambiente** `GLTD_AGENT_GROK` / `GLTD_AGENT_GEMINI` / `GLTD_AGENT_OPENCODE`
   - Suporta templates `{prompt}` (substituição inline) e `{prompt_file}` (arquivo temporário)
   - Modo shell: `shell=True`

2. **CLIs nativos** detectados automaticamente no PATH e diretórios conhecidos
   - `~/.opencode/bin/` (opencode)
   - `~/.nvm/versions/node/*/bin/` (grok, gemini via npm/nvm)
   - `GLTD_AGENT_EXTRA_PATH` (caminhos extras separados por `:`)

3. **Ollama** como fallback (modelos locais)
   - Modelos configuráveis via `GLTD_OLLAMA_GROK_MODEL`, `GLTD_OLLAMA_GEMINI_MODEL`,
     `GLTD_OLLAMA_DEEPSEEK_MODEL`

## Configuração

### Usar opencode (recomendado para DeepSeek)

Não requer configuração se o binário `opencode` estiver no PATH ou em
`~/.opencode/bin/`. Comportamento padrão: `opencode run "prompt"`.

#### Configurações do provedor (API keys)

```bash
# Credenciais do DeepSeek no opencode
opencode providers add deepseek --api-key "sk-..."
opencode providers set-default deepseek

# Verificar
opencode providers list
```

#### Opções extras (via env var)

```bash
export GLTD_AGENT_OPENCODE="opencode run --model deepseek-v4-pro {prompt_file}"
```

### Usar outros agentes

```bash
# Gemini
export GLTD_AGENT_GEMINI="gemini -p -y {prompt_file}"

# Grok
export GLTD_AGENT_GROK="grok -p {prompt_file} --always-approve --output-format json"
```

### Variáveis de ambiente completas

| Variável                    | Função                                           |
|-----------------------------|--------------------------------------------------|
| `GLTD_AGENT_GROK`           | Template de comando para o agente grok           |
| `GLTD_AGENT_GEMINI`         | Template de comando para o agente gemini         |
| `GLTD_AGENT_OPENCODE`       | Template de comando para opencode-deepseek4      |
| `GLTD_AGENT_EXTRA_PATH`     | Diretórios adicionais (`:` separados) para buscar binários |
| `GLTD_OLLAMA_GROK_MODEL`    | Modelo ollama para grok (default: `llama3.2`)    |
| `GLTD_OLLAMA_GEMINI_MODEL`  | Modelo ollama para gemini (default: `llama3.2`)  |
| `GLTD_OLLAMA_DEEPSEEK_MODEL`| Modelo ollama para deepseek (default: `deepseek-r1`) |

## Fluxo de uma tarefa de agente

### 1. Criar a tarefa

Menu **Tarefas → Nova tarefa para agente** ou botão "Tarefa para agente" na tela Home.

Escreva a descrição no campo **Descrição da tarefa**. Seja específico:

```
Configurar o servidor 192.0.2.1:
1. Acessar via SSH como root
2. Instalar e configurar o MariaDB
3. Criar banco de dados "app_producao"
4. Criar usuário "app_user" com senha segura
5. Configurar backup diário com cron
```

### 2. Executar

Clique **▶ Play / Executar**. A tarefa roda em background (thread separada,
timeout de 180s). Status muda para `running` → `done` ou `failed`.

### 3. Verificar resultado

O output aparece no campo **Output do agente**. Se o agente retornar exit code 0,
status = `done`. Qualquer erro vai para o mesmo campo com status `failed`.

### 4. Tarefas relacionadas

Use **＋ Tarefa relacionada** para criar subtarefas encadeadas (ex: uma tarefa
de análise seguida de uma de implementação).

## Resolução de problemas

### "Nenhum executor local encontrado"

O agente não está instalado ou não foi encontrado no PATH. Verifique:

```bash
which opencode    # Deve retornar o caminho
which gemini      # Se usar gemini
which grok        # Se usar grok
```

Se os binários existem mas o GLTD Notes não os encontra, defina:

```bash
export GLTD_AGENT_EXTRA_PATH="$HOME/.opencode/bin:$HOME/.nvm/versions/node/*/bin"
```

E reinicie o aplicativo.

### Timeout (180s)

Tarefas complexas podem exceder o timeout. Aumente no código
(`main_window.py:1281`) ou divida a tarefa em subtarefas menores.

### Erro "pulling manifest" do Ollama

Significa que o Ollama está instalado mas o GLTD Notes está tentando usá-lo como
fallback. O modelo `llama3.2` não existe ou o registry está inacessível.

**Solução:** Configure um dos `GLTD_AGENT_*` acima para forçar o uso do CLI desejado:

```bash
export GLTD_AGENT_OPENCODE="opencode run {prompt_file}"
```

### opencode no modo errado (TUI)

Se o opencode abrir interface interativa em vez de executar em batch, verifique
se o comando padrão inclui `run`:

```bash
# Correto (headless batch)
opencode run "sua tarefa"

# Errado (abre TUI)
opencode "sua tarefa"
```

O GLTD Notes já usa `opencode run` por padrão.

## Estrutura de dados da tarefa

Cada tarefa de agente é armazenada como JSON no campo `body` da nota:

```json
{
  "version": 1,
  "description": "Descreva o que o agente deve fazer…",
  "agent": "opencode-deepseek4",
  "status": "done",
  "output": "resultado da execução...",
  "executed_at": "2026-07-28T12:00:00.000Z",
  "parent_id": null,
  "related_ids": []
}
```

- **description**: entrada para o agente (o prompt)
- **agent**: `grok`, `gemini` ou `opencode-deepseek4`
- **status**: `pending` | `running` | `done` | `failed` | `skipped`
- **output**: stdout + stderr do processo
- **parent_id**: tarefa pai (para subtarefas)
- **related_ids**: subtarefas vinculadas

## API REST

O endpoint de agent tasks aceita criação e status via REST:

```bash
KEY="sua-api-key"

# Criar tarefa
curl -s -H "X-API-Key: $KEY" -H 'Content-Type: application/json' \
  -d '{"title":"Setup servidor","description":"Instalar e configurar...","agent":"opencode-deepseek4"}' \
  http://127.0.0.1:8765/api/v1/notes

# Ver status
curl -s -H "X-API-Key: $KEY" \
  http://127.0.0.1:8765/api/v1/notes/{note_id}
```

> A execução (Play) só está disponível via GUI. A API permite criar e consultar.

## Dicas para prompts eficazes com DeepSeek

1. **Seja específico** sobre arquivos, paths e comandos esperados
2. **Divida tarefas grandes** em subtarefas (use "Tarefa relacionada")
3. **Inclua contexto** como senhas, IPs e versões de software
4. **Especifique restrições** ("não delete bancos de dados existentes")
5. **Peça verificação** ao final ("confirme que o serviço está rodando")

Exemplo de prompt bem estruturado:

```
Tarefa: Configurar MariaDB no servidor 192.0.2.1

Contexto:
- Acesso SSH: root@192.0.2.1
- IPs que devem acessar: 198.51.100.10, 203.0.113.5, 127.0.0.1

Passos:
1. Conectar via SSH
2. Verificar se o MariaDB está instalado (instalar se necessário)
3. Configurar bind-address para ouvir em todas as interfaces
4. Configurar o firewall (iptables/ufw) para permitir porta 3306 apenas dos IPs listados
5. Criar usuário root com acesso remoto dos IPs autorizados
6. Executar GRANTs necessários nos bancos existentes

Restrições:
- NÃO deletar databases existentes
- NÃO remover usuários existentes
- Manter backup dos arquivos de configuração originais

Verificação:
- Confirmar que o MariaDB está ouvindo na porta 3306
- Testar conexão de um dos IPs autorizados
```

## Licença

MIT — mesmo do projeto GLTD Notes.
