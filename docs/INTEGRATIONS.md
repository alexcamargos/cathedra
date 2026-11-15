# Contratos de Integracao Externa, Clientes LLM e Infraestrutura

## 1. Protocolo do Cliente LLM (`src/mba_wiki/agents/llm_client.py`)
Nenhum no do pipeline instancia SDKs de provedores diretamente. Todos os nos recebem uma implementacao do protocolo abaixo via injecao de dependencia, permitindo execucao com CLI local, roteamento de modelos especializados e testes offline com `FakeLLMClient`:

```python
from typing import Protocol, TypeVar
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class StructuredLLMClient(Protocol):
    def generate_structured(
        self,
        system_prompt: str,
        user_prompt: str,
        response_model: type[T],
        temperature: float = 0.2,
    ) -> T: ...

    def generate_text(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.3,
    ) -> str: ...
```

## 2. Cliente Local Antigravity CLI (`AGYCLIClient`)
A implementacao de producao (`AGYCLIClient`) utiliza a CLI nativa em subprocesso, incorporando:
- **Transporte via stdin:** Para prompts extensos (slides densos e transcricoes completas), os dados sao direcionados via canal `stdin` em UTF-8 ou arquivo temporario em `scratch/`, contornando a restricao de 32 KB da linha de comando Win32.
- **Roteamento de Modelos Especializados:** Suporte aos modelos configurados em `config.py` (`llm_model` para geracao geral e `llm_model_auditor` para auditoria factual adversarial mais profunda).
- **Extracao Resiliente de JSON:** Mecanismo de captura por envelope delimitador `{...}` para filtrar possiveis mensagens preliminares ou logs de diagnostico emitidos pela ferramenta CLI.

## 3. Cliente Gemini REST e credenciais
O cliente Gemini carrega `GEMINI_API_KEY` a partir da configuracao ou do ambiente. A chave e mantida como `SecretStr` e enviada no cabecalho `x-goog-api-key`, sem fazer parte da URL. Erros de rede e de resposta nao incluem o corpo retornado nem o detalhe bruto da excecao; erros HTTP preservam o codigo de status. Metadados de uso invalidos sao ignorados.

`SecretStr` reduz a exposicao em representacoes e serializacao, mas nao substitui a protecao do arquivo `.env`, do ambiente ou do processo. Uma credencial exposta precisa ser revogada ou rotacionada no provedor.

## 4. Infraestrutura de Transcricao e Aceleracao CUDA
O modulo de transcricao desacoplada (`src/mba_wiki/transcription/`) integra dependencias de baixo nivel para execucao eficiente no Windows:
- **Auto-provisao de FFmpeg:** Localizacao automatica ou download e extracao de executavel estatico minimalista para `%LOCALAPPDATA%\cathedra\bin` sem necessidade de instalacao manual prévia.
- **Injecao Dinamica de DLLs NVIDIA:** Localizacao e registro dinamico dos pacotes `nvidia-cublas-cu12` e `nvidia-cudnn-cu12` via `os.add_dll_directory()` no Windows antes da inicializacao do backend CTranslate2 / Faster-Whisper.
- **Fallback Gracioso para CPU:** Inspecao da contagem de dispositivos CUDA operacionais (`ctranslate2.get_cuda_device_count()`), alternando para quantizacao `int8` em CPU quando GPU dedicada nao estiver disponivel.
