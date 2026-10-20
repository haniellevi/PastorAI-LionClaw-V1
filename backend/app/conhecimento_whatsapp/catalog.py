"""Closed search tool: no model-provided tenant, identity, audience or document."""
import re
from unicodedata import category
from pydantic import BaseModel, ConfigDict, Field, field_validator
from app.prayer.catalog import normalized

HELP='Envie CONHECIMENTO buscar TERMO para consultar documentos oficiais. Publicação e exclusão exigem o painel autenticado.'


class SearchTool(BaseModel):
    model_config=ConfigDict(extra='forbid')
    consulta: str=Field(min_length=1,max_length=200)

    @field_validator('consulta')
    @classmethod
    def safe_query(cls,value):
        if not value.strip() or any(category(c)=='Cc' for c in value):
            raise ValueError('Consulta inválida')
        return value


def route(text):
    # Normalize only command words; original query is data for lexical search.
    match=re.fullmatch(r'\s*(\S+)\s+(\S+)\s+(.+?)\s*',text,re.DOTALL)
    if match and match[3].strip() and normalized(match[1])=='conhecimento' and normalized(match[2])=='buscar':
        return 'search',match[3]
    value=' '.join(normalized(text).split())
    return ('help',None) if value in {'conhecimento','conhecimento buscar'} else ('none',None)


def execute(db,usuario,tool: SearchTool):
    from app.services.conhecimento import buscar
    return buscar(db,usuario,tool.consulta,limite=3)
