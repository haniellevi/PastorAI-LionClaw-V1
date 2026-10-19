"""Decisões provisórias centralizadas; aguardam confirmação pastoral.

Admin publica; pastor revisa somente a área sob sua responsabilidade.
Elaboração restrita a admin; público deve ser escolhido no novo snapshot.
Um papel nunca implica acesso universal ao conteúdo publicado.
"""
from typing import Final

PUBLICADORES: Final = frozenset({'admin'})
REVISORES: Final = frozenset({'admin', 'pastor'})
PUBLICO_ELABORACAO: Final[tuple[str, ...]] = ()
PUBLICO_VISITANTE: Final = 'institucional_publico'
RESPOSTA_SEM_EVIDENCIA: Final = (
    'Não há informação oficial suficiente para responder com segurança. '
    'Encaminhe a dúvida ao responsável da área.'
)
