# Contratos de Integracao Externa e Mocks

## 1. Protocolo do Cliente LLM (`src/mba_wiki/agents/llm_client.py`)
Nenhum no do pipeline deve instanciar SDKs de provedores diretamente. Todos os nos devem receber uma implementacao do protocolo abaixo via injecao de dependencia, permitindo testes offline com `FakeLLMClient`:

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