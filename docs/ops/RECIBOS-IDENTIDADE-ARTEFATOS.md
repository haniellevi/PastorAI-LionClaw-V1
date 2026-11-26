# Recibo administrativo de identidade de artefato

O utilitário local `tools/artifact_identity_receipt.py` registra a comparação
entre a identidade esperada e a observada de um único componente. Não coleta
dados, acessa serviços ou participa do release.

O responsável fornece os dados sanitizados da observação; a identidade esperada
vem de um recibo de build local previamente verificado por ele. Use o digest do
mesmo tipo de artefato nos dois lados da comparação (por exemplo, não compare o
digest de um manifesto de imagem com o hash de um arquivo).

## Entrada e registro local

Prepare um JSON local com `component` (`backend` ou `frontend`), `expected`
(recibo de build) e `observed` (evidência de observação). Cada evidência contém
exclusivamente:

| Campo | Formato |
| --- | --- |
| `component` | Mesmo componente solicitado |
| `revision` | SHA Git completo, 40 caracteres hexadecimais minúsculos |
| `digest` | `sha256:` seguido de 64 caracteres hexadecimais minúsculos |
| `evidence_id` | UUID canônico opaco da evidência, sem identificação pessoal |
| `evidence_at` | Data e hora da evidência em UTC, formato `AAAA-MM-DDTHH:MM:SSZ` |

Não inclua nomes de pessoas, endereços, texto livre, configuração, segredos ou
detalhes operacionais. Se faltar uma evidência, deixe seu campo ausente ou
`null`. Não invente valores.

Com Python 3.13, execute o utilitário localmente passando o caminho absoluto de
um diretório privado existente como único argumento e o JSON pela entrada
padrão. O diretório deve pertencer ao usuário, ter modo `0700` e ficar fora
da árvore do projeto. Cabe ao responsável escolher armazenamento persistente,
fora de qualquer outro repositório ou área servida, compartilhada ou
sincronizada publicamente. Não faça upload nem commit dos recibos reais.

O arquivo JSON de saída (modo `0600`) tem nome UUID, `schema_version: 1`,
identidade e data UTC do próprio recibo, componente, evidências validadas e
`status`. A gravação publica somente o arquivo completo e não substitui um
recibo anterior. A execução não imprime valores. Os códigos de saída são:

- `0`: gravação concluída, não necessariamente identidades correspondentes.
- `1`: entrada recusada ou falha antes de criar um novo recibo.
- `2`: o arquivo final foi criado, mas houve falha de I/O posterior;
  sua durabilidade local não está confirmada. Verifique o diretório privado
  antes de decidir se é necessário registrar de novo. Não repita automaticamente
  nem apague ou sobrescreva o recibo existente. Uma falha na limpeza do arquivo
  temporário pode deixar dois nomes privados referentes ao mesmo arquivo.

## Interpretação

- `correspondente`: ambas as evidências são válidas em formato, referem-se
  ao componente solicitado e têm SHA e digest iguais.
- `divergente`: ambas são válidas em formato e pelo menos um desses valores
  diverge.
- `desconhecido`: falta uma evidência válida; a ausente ou inválida fica
  registrada como `null`, sem conservar o conteúdo inválido. Uma entrada
  estruturalmente ambígua ou sem componente válido é recusada sem criar arquivo.

A comparação é puramente local. Igualdade dos dados fornecidos não autentica
as evidências ou seus autores, não verifica os artefatos em si e não prova
independentemente a instalação, integridade, atividade ou versão viva.
O recibo é histórico e não observa mudanças posteriores. Permissões de arquivo
restringem acesso local; não substituem o armazenamento privado sob
responsabilidade administrativa nem tornam o registro inviolável.

O utilitário não consulta Git, infraestrutura, banco, painel, APIs ou qualquer
ambiente de execução. Não autoriza nem altera release, candidato, janela ou
controles operacionais. Os testes do CI usam apenas dados fictícios descartáveis.
