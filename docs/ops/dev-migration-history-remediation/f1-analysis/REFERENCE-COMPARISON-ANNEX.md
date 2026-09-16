# Anexo F1, comparação catalográfica DEV x referência PG17

## Método e limite

Este anexo vincula a análise a um replay local, offline e descartável das 77
migrations no SHA base. O replay usa o harness versionado do repositório. A
coleta final executa somente a seção catalográfica do SQL F1 congelado, depois
de provar que os dois ledgers locais de referência estão ausentes. Por isso, o
SQL F1 byte-idêntico não é executado nessa referência: seus guards exigem
`EXPECTED_33` e `EXPECTED_6`, enquanto o harness exige os dois ledgers ausentes
após cada migration. A adaptação local falha fechada se qualquer ledger surgir;
ela não cria, mascara, preenche nem compara ledgers como equivalentes.

O SQL F1 congelado permanece SHA-256 `8829decd0f0101329058ad07900ce7b7ca8b1c4fe5695f4e3cec05cff4bf288c` e o agregado F1 congelado
permanece SHA-256 `956187b9711ea9d67e9f8fdf31c3980e3ebbf64da98401c275f1dc80d2a91a29`. A fonte DEV é a transcrição sanitizada já
verificada, sem cópia dos seus bytes para este repositório. Chave segura é o
SHA-256 de `record_type`, `schema_ref`, `relation_ref`, `object_ref` e ordinal
opaco de ocorrência. O anexo nunca imprime esses componentes, definições,
binding, dado de domínio ou nome/OID de role inesperada.

Antes da comparação, parser e comparador aplicam a mesma tabela de contrato
DEV. Nesta rodada, `SEALED_F1` aceita eco interno de rollback `0/1` somente
quando a regeneração local valida arquivo regular, modo `0600`, hash pinado e
índice DEV pinado. `STRICT_FUTURE` exige o eco interno; ele não herda a
exceção selada. O contrato exige os dois ledgers nas cardinalidades esperadas,
seis fingerprints nativos, preflight antes do rollback e nenhum catálogo após
o terminal. Nenhum caminho pessoal ou byte da transcrição entra neste anexo.

O índice opaco V3 inclui também `definition_sha256`. Em
`CATALOG_SCHEMA` e `CATALOG_RELATION`, ele normaliza somente `acl_state`; nos
outros record types ele continua a cobrir o payload completo. Assim,
`ACL_ONLY` significa que toda diferença atribuível da linha se restringe a
`acl_state`. Uma diferença desse tipo pode decorrer da execução local versus
o contrato de plataforma Supabase e, isoladamente, não prova drift DEV. Ela
continua conservadoramente parcial porque sua igualdade não é `EQUAL`. Grants
diretos, default ACL, grantee e qualquer outra definição nunca recebem o rótulo
`ACL_ONLY` por essa normalização.

O traço V2 separa, por chave segura, `INTRODUCED`, `RETIRED` e `MODIFIED`. Uma
chave do delta que não chega ao catálogo final não é descartada por contagem ou
por nome: ela só ganha expectativa de ausência se o próprio traço a marca como
retirada na mesma migration ou em migration posterior. Sem essa retirada
direcional, `UNRESOLVED_REFERENCE_GAP` mantém a linha diferente e impede
`PHYSICAL_EFFECTS_PRESENT` ou `PHYSICAL_EFFECTS_ABSENT`, exceto pelo teto
independente de `NOT_SCHEMA_DECIDABLE`. Essa regra cobre remoção e substituição
sem uma allowlist de objetos transitórios.

`ANNEX_CANONICAL_SHA256=944f77ac4e84421cf1ba89e6d0dc7bb52e314721ff5e7222baaaa611838a6e5e`

## Cobertura global

| Origem | Registros catalográficos opacos | Igualdade de payload | Ausente em DEV | Mesmo key, payload divergente |
| --- | ---: | ---: | ---: | ---: |
| Referência PG17 | `1901` | `1209` | `642` | `50` |
| DEV sanitizado | `2959` | não aplicável | não aplicável | não aplicável |

As contagens globais são comparação de catálogo por chave segura. Não são
comparação de ledger, prova de aplicação nem autorização de epoch, cutover ou
alteração de ambiente.

## Comparação por migration

Em `TIPO a/b`, `a` é a quantidade de expectativas satisfeitas e `b` a
quantidade de chaves atribuídas ao delta local: uma chave final exige payload
DEV idêntico; uma retirada terminal exige a sua ausência em DEV. O campo
`Ciclo de vida` reporta quantas expectativas de ausência foram provadas pelo
traço e quantas lacunas ficaram sem retirada direcional. `NO_STRUCTURAL_TRACE`
é esperado para efeitos só de dados, reconciliação ou no-op condicional. A
classificação final ainda respeita esse teto: igualdade estrutural não
transforma DML em prova de aplicação.

As contagens de auditoria estática já registradas na matriz são uma assinatura
de fonte, não uma substituição desta comparação. Três pontos permanecem
explicitamente separados: o item 5 mantém `REL 3/3` na fonte e tem
`CATALOG_RELATION 0/3` por chave DEV/ref; o item 30 mantém seis alvos
relacionais na fonte e continua não decidível por DML, enquanto o traço só
atribui quatro deltas de metadado relacional; o item 39 mantém `CON 13/13` e
`IDX 11/11` de comandos explícitos. Para este último, o coletor F1 registra
mais três índices de suporte a constraints, por isso a linha catalográfica é
`CATALOG_INDEX 14/14`; helpers `pg_temp` não entram no coletor persistente.

| # | Migration fonte | Chaves seguras SHA-256 | Hash referência | Hash DEV | Igualdade | Ciclo de vida | Natureza da diferença | Contagens por record_type, DEV/ref | Classificação F1 |
| ---: | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `20260701_014654_evt6_google_event_dedup_index.sql` | `16c46551536a90bfa408c4c10f525654e66100f2738300dbf453bca8fecbdf6e` | `08bba83d3a3c5519d513396776cbd484ca26a7b9e1e8563fddfc33cd93238faf` | `25372064b8c26b92402b250314a1f8c57df164d068e80321ffdedab8224fff1c` | EQUAL | `TERMINAL_RETIREMENT=0; UNRESOLVED_REFERENCE_GAP=0` | `NONE` | CATALOG_INDEX 1/1 | `PHYSICAL_EFFECTS_PRESENT` |
| 2 | `20260701_164352_evt7_events_notificado_em_aviso_confirmacao.sql` | `53dbe43f054957339bab6c24c3556e27fd020817c71e312299a4b1c218e53417` | `2efe4f70357fb057e7c0a36adf7c4b17d26ebaa69931d52d9a091c0fb05136d3` | `8f03166e610b0dcdaf70301679506cacb66683ce3cc30a5017aaf2327fd0b95f` | EQUAL | `TERMINAL_RETIREMENT=0; UNRESOLVED_REFERENCE_GAP=0` | `NONE` | CATALOG_COLUMN 1/1 | `PHYSICAL_EFFECTS_PRESENT` |
| 3 | `20260701_193000_evt7_pr2_agenda_alert_recipients.sql` | `abd6511556b951c0c1aa5690bb3ceedb18e0adfe8479f5ae969f02b753b87f6a` | `9ae181ef8c15434d74f29f7b231b6258a3fbe9329168be12b527cf33c8094727` | `540298d6d08bae2467612adbdc1996df8ff2063cbf56e7b8099d0a44dbe51729` | DIFFERENT_OR_PARTIAL | `TERMINAL_RETIREMENT=0; UNRESOLVED_REFERENCE_GAP=0` | `ACL_ONLY` | CATALOG_COLUMN 7/7; CATALOG_CONSTRAINT 2/2; CATALOG_INDEX 3/3; CATALOG_RELATION 0/1; CATALOG_RLS_POLICY 1/1 | `PARTIAL_OR_CONFLICTING` |
| 4 | `20260703_123803_celula_schema_base_pr1.sql` | `3e06f31239a71a7f4013b0b9eecd81f4e9ad4059cde84e477aa67a4c5dda66fd` | `68bdabe25537f1ee2f269a2c7d26f10eb0c5ec4786d89e1d66fac5bed7a2e06f` | `6f79ab1b678a2f98b8ad296ff70a767a4442872f5b86239ae527c7adc99244bc` | DIFFERENT_OR_PARTIAL | `TERMINAL_RETIREMENT=0; UNRESOLVED_REFERENCE_GAP=0` | `ACL_ONLY` | CATALOG_COLUMN 15/15; CATALOG_CONSTRAINT 7/7; CATALOG_INDEX 5/5; CATALOG_RELATION 0/1; CATALOG_RLS_POLICY 1/1; CATALOG_TYPE 1/1 | `PARTIAL_OR_CONFLICTING` |
| 5 | `20260704_100000_celula_pr2_reuniao_presenca_expectativa.sql` | `87912eab9a5d3e8c504147afc13bcaa51dd67be0c0342c8a9c1783bb2c248515` | `14b1282973b838da3cdcc940f17b60cf1d38740e52585479fb835f85e13a21c6` | `09ba851ed1d528b0a4db885c1c923cd89a552de46c88a57694b283746223f03d` | DIFFERENT_OR_PARTIAL | `TERMINAL_RETIREMENT=0; UNRESOLVED_REFERENCE_GAP=0` | `ACL_ONLY` | CATALOG_COLUMN 25/25; CATALOG_CONSTRAINT 14/14; CATALOG_INDEX 13/13; CATALOG_RELATION 0/3; CATALOG_RLS_POLICY 3/3 | `PARTIAL_OR_CONFLICTING` |
| 6 | `20260705_120000_celula_pr3_reuniao_relatorio_campos.sql` | `20cef7cb0499984e319412cf5e79cf49b2cb6b5a6ae3c001e683b88a7b8ba218` | `f3f1d7e8ac71d66eaca4aff4dd84ecffcf6ae9b2c3231a903fdcae1d8b85d5f4` | `137ccb98a96d259e08cc30d0ca17261be03cb16065a1ed363b15385662e3fb4d` | EQUAL | `TERMINAL_RETIREMENT=0; UNRESOLVED_REFERENCE_GAP=0` | `NONE` | CATALOG_COLUMN 6/6; CATALOG_CONSTRAINT 2/2; CATALOG_INDEX 1/1 | `PHYSICAL_EFFECTS_PRESENT` |
| 7 | `20260705_120100_celula_pr3_reuniao_registro.sql` | `41146607d1ad2507f622f4035f2912aace06b3ddeea5dff1747278ef5412f81d` | `1d1c49cbafe4d7a365747f8c4180ad07bf89ba811383d44ccf176e65112d97e9` | `08c3cf0009267e025d33ee6ede1efd0668b1d3451526a1d8cce68ec4e0dc6dfc` | DIFFERENT_OR_PARTIAL | `TERMINAL_RETIREMENT=0; UNRESOLVED_REFERENCE_GAP=0` | `ACL_ONLY` | CATALOG_COLUMN 9/9; CATALOG_CONSTRAINT 6/6; CATALOG_INDEX 3/3; CATALOG_RELATION 0/1; CATALOG_RLS_POLICY 1/1 | `PARTIAL_OR_CONFLICTING` |
| 8 | `20260705_120200_celula_pr3_visitante.sql` | `b27f9627d5f1189b9462d0fcc55a716d00260c7c35dd26b911fcfccbb1497d5a` | `f71c06945f99bfa1324a108b33ae1331635daa316c42fd030b10d8f3bb4ea605` | `3f5d3ba799a86f1aaed0009ad72af9779c3a6b3125c1309693ac5f78d0c4defe` | DIFFERENT_OR_PARTIAL | `TERMINAL_RETIREMENT=0; UNRESOLVED_REFERENCE_GAP=0` | `ACL_ONLY` | CATALOG_COLUMN 9/9; CATALOG_CONSTRAINT 4/4; CATALOG_INDEX 3/3; CATALOG_RELATION 0/1; CATALOG_RLS_POLICY 1/1 | `PARTIAL_OR_CONFLICTING` |
| 9 | `20260705_120300_celula_pr3_solicitacao_evento.sql` | `3abde3a86ecfd7135f913eb1f10b8e9f3e5d919d2030e9cef9682487dae7c1e1` | `c32d18142c3a8b29fc0a5189556b3bc7aaf8c3477999efeb609b4884588adac7` | `bb770c516e5a5f0afc6e5ca70b1b39f22c7b7accf56aef5fabaef1f872f31124` | DIFFERENT_OR_PARTIAL | `TERMINAL_RETIREMENT=0; UNRESOLVED_REFERENCE_GAP=0` | `DEFINITION_OR_MISSING_REFERENCE` | CATALOG_COLUMN 25/25; CATALOG_CONSTRAINT 13/13; CATALOG_FUNCTION 0/1; CATALOG_INDEX 7/7; CATALOG_RELATION 0/2; CATALOG_RLS_POLICY 2/2; CATALOG_TRIGGER 1/1 | `PARTIAL_OR_CONFLICTING` |
| 10 | `20260705_120400_celula_pr3_aviso.sql` | `141bf879b87c74b89e6b5177b701cd91660531bf8dff4584bb694770cf80c944` | `8439d550c4766d4fe78ccd82e048539a14e3d8cd4994955e150690a603c367e4` | `bfba38688bdf4f0589f6d81b609b62d55dea155f22494ed9f2477cbea062ee37` | DIFFERENT_OR_PARTIAL | `TERMINAL_RETIREMENT=0; UNRESOLVED_REFERENCE_GAP=0` | `ACL_ONLY` | CATALOG_COLUMN 13/13; CATALOG_CONSTRAINT 6/6; CATALOG_INDEX 3/3; CATALOG_RELATION 0/1; CATALOG_RLS_POLICY 1/1 | `PARTIAL_OR_CONFLICTING` |
| 11 | `20260705_120500_celula_pr3_material.sql` | `5557f25795f196737e968728d0b2bffbd763877056e6a36bfb74b4c3cebc0015` | `7f8d05d7d5182c76c11106ca8f3d2e93fb55a8bd83ad95a53ccc227113db8d7e` | `362ec7694191727d5dde5dd138a1a71e35b39993fe2ed6e22b101a658372bb1d` | DIFFERENT_OR_PARTIAL | `TERMINAL_RETIREMENT=0; UNRESOLVED_REFERENCE_GAP=0` | `ACL_ONLY` | CATALOG_COLUMN 11/11; CATALOG_CONSTRAINT 3/3; CATALOG_INDEX 2/2; CATALOG_RELATION 0/1; CATALOG_RLS_POLICY 1/1 | `PARTIAL_OR_CONFLICTING` |
| 12 | `20260705_120600_celula_pr3_multiplicacoes_evolucao.sql` | `fe358b3f5f722cff9b96cc94d712b2c124080757e2bf2df5009ef82d7599af4c` | `df0c2a6123605bb44240b13fdae3fb000cb73259409883a1f4b19a7274d30fac` | `c76dae28f81fc7d40854d50781cd82974399f778283c1d1ef1b9de52fababdcd` | DIFFERENT_OR_PARTIAL | `TERMINAL_RETIREMENT=0; UNRESOLVED_REFERENCE_GAP=0` | `DEFINITION_OR_MISSING_REFERENCE` | CATALOG_COLUMN 4/5; CATALOG_CONSTRAINT 2/3; CATALOG_INDEX 3/3 | `PARTIAL_OR_CONFLICTING` |
| 13 | `20260706_221311_pessoas_apto_lider_e_converte_legado_tipo_lider.sql` | `707621d8a8cdc2f0cb0411d658bc25e2d0ed9d1222644169754eeb0bb8de82f9` | `f5074866c15fa6434ef184bfb2a9ff96d340ad0cfda73dc826c41f3f9b75f607` | `81343296f0c4c6dfb6b9d035ef5d559964544c6463cf0cbe2904076607342bf3` | EQUAL | `TERMINAL_RETIREMENT=0; UNRESOLVED_REFERENCE_GAP=0` | `NONE` | CATALOG_COLUMN 1/1 | `NOT_SCHEMA_DECIDABLE` |
| 14 | `20260706_230000_evt8_pr1_notify_config.sql` | `2c18860e4a4f64c0a9100198b9e16f9098f5fbfd336dae9d6bac16cc3b991061` | `89a344e7627da618b67bc1ef025d79591eafda91a49ee83729c0389f69ac69a2` | `e340ef53d072370e01c7ed5462b76abbbd6801882b25b1c9ee5569e5f31f3dc7` | DIFFERENT_OR_PARTIAL | `TERMINAL_RETIREMENT=0; UNRESOLVED_REFERENCE_GAP=0` | `ACL_ONLY` | CATALOG_COLUMN 9/9; CATALOG_CONSTRAINT 6/6; CATALOG_INDEX 5/5; CATALOG_RELATION 0/1; CATALOG_RLS_POLICY 1/1 | `PARTIAL_OR_CONFLICTING` |
| 15 | `20260707_011455_igreja_logo_branding.sql` | `c1eb5e462903e2273a1b1b68942514830a534768c5b326a60792e13702226883` | `549ad31dc1fcd5f9a6d163a216ddeee1c9ea01c633275dada83eb70de2f20450` | `bed67fd487fef226008e2a6f3fb64356f470a769ec46e48f80cea8034935d5f1` | EQUAL | `TERMINAL_RETIREMENT=0; UNRESOLVED_REFERENCE_GAP=0` | `NONE` | CATALOG_COLUMN 1/1; CATALOG_FUNCTION 1/1; CATALOG_RELATION 1/1; CATALOG_RLS_POLICY 1/1 | `PARTIAL_OR_CONFLICTING` |
| 16 | `20260708_160128_sec3a_app_users_password_changed_at.sql` | `9aff2e4ea89c50354f1e2a0f1da321e169ca39af8384fcdca9e39806a194ff2c` | `0bdc68b8869a7d2acaba1d31b5b1ff775e3041655dc0404194f5e9f28e5169d8` | `8238556fd4bec24cc64eda4fd9560927088fc5a28f29850b86a2ba2d45961612` | EQUAL | `TERMINAL_RETIREMENT=0; UNRESOLVED_REFERENCE_GAP=0` | `NONE` | CATALOG_COLUMN 1/1 | `PHYSICAL_EFFECTS_PRESENT` |
| 17 | `20260708_164756_backfill_celula_membro_canonico.sql` | `9b84872805ef942add460d53dc3ab7f609413493f7dc0808fb161f81725851e4` | `5e2c5befd6ab097bcd690cd60d0ddc46eacd1f0edef3337bda3204a7ff2976e4` | `b0da187af05a2bb45ff59051f366f2050cfcad97585bb15fea7247366f0d9eee` | NO_STRUCTURAL_TRACE | `NO_STRUCTURAL_TRACE` | `NO_STRUCTURAL_TRACE` | NONE 0/0 | `NOT_SCHEMA_DECIDABLE` |
| 18 | `20260708_172106_sec3b_password_reset_tokens_single_use.sql` | `45b6fd967e81de23173da4c5069ad237756c2051463bb0159782f45b61d296b9` | `1bc7f782304e968de4bd5d6ce1a1d0fc23b9ad4df63970585a13192e2dcca2ba` | `ee6262c976e4365a046392e4d3c7ee38453ceee99da802ae9ed2b73e795e0a63` | EQUAL | `TERMINAL_RETIREMENT=1; UNRESOLVED_REFERENCE_GAP=0` | `NONE` | CATALOG_COLUMN 6/6; CATALOG_CONSTRAINT 2/2; CATALOG_INDEX 4/4; CATALOG_RELATION 1/1; CATALOG_RLS_POLICY 1/1 | `PHYSICAL_EFFECTS_PRESENT` |
| 19 | `20260708_221808_igreja_dono_id_grant_update.sql` | `9b84872805ef942add460d53dc3ab7f609413493f7dc0808fb161f81725851e4` | `5e2c5befd6ab097bcd690cd60d0ddc46eacd1f0edef3337bda3204a7ff2976e4` | `b0da187af05a2bb45ff59051f366f2050cfcad97585bb15fea7247366f0d9eee` | NO_STRUCTURAL_TRACE | `NO_STRUCTURAL_TRACE` | `NO_STRUCTURAL_TRACE` | NONE 0/0 | `PARTIAL_OR_CONFLICTING` |
| 20 | `20260709_204500_sec4_agent_event_idempotency_marker_uidx.sql` | `518f4fc657847acb7f8aa831f1271b0356d930b7e357384e0c98b482d76fed9d` | `569ca0a8d0600cba395fbdbe0d9c9e51cf593a37ae1344b42f9aea99fa16cfb4` | `a5311bf9ed4b4c2e7d267a9270a6eceac1ae070ab7aa3d847b65d3cea991c526` | EQUAL | `TERMINAL_RETIREMENT=0; UNRESOLVED_REFERENCE_GAP=0` | `NONE` | CATALOG_INDEX 1/1 | `PHYSICAL_EFFECTS_PRESENT` |
| 21 | `20260711_023515_backfill_pessoa_tipo_membro_por_vinculo_ativo.sql` | `9b84872805ef942add460d53dc3ab7f609413493f7dc0808fb161f81725851e4` | `5e2c5befd6ab097bcd690cd60d0ddc46eacd1f0edef3337bda3204a7ff2976e4` | `b0da187af05a2bb45ff59051f366f2050cfcad97585bb15fea7247366f0d9eee` | NO_STRUCTURAL_TRACE | `NO_STRUCTURAL_TRACE` | `NO_STRUCTURAL_TRACE` | NONE 0/0 | `NOT_SCHEMA_DECIDABLE` |
| 22 | `20260711_152127_reclassifica_pessoa_do_numero_whatsapp_fora_de_membro.sql` | `9b84872805ef942add460d53dc3ab7f609413493f7dc0808fb161f81725851e4` | `5e2c5befd6ab097bcd690cd60d0ddc46eacd1f0edef3337bda3204a7ff2976e4` | `b0da187af05a2bb45ff59051f366f2050cfcad97585bb15fea7247366f0d9eee` | NO_STRUCTURAL_TRACE | `NO_STRUCTURAL_TRACE` | `NO_STRUCTURAL_TRACE` | NONE 0/0 | `NOT_SCHEMA_DECIDABLE` |
| 23 | `20260711_224403_celula_solicitacao_e13_open_unique.sql` | `d6555cbb9b14a09761c9c79aeaf572db2a8e2fac9c989b1f82db963281ce42e4` | `470b8bc0dc7e0822289128fa6b70636f81bd1dc48100fa34bfe5e4f27493dbe3` | `e91102679d6bfb019fbfaf3e7925b8cbbfad06d157f465d592808f81333919ad` | EQUAL | `TERMINAL_RETIREMENT=0; UNRESOLVED_REFERENCE_GAP=0` | `NONE` | CATALOG_INDEX 2/2 | `PHYSICAL_EFFECTS_PRESENT` |
| 24 | `20260713_013054_pessoa_arquivamento_schema.sql` | `cf0e865d93734265c823e28dcf2f6add7e5a71ea0a85c8cc3576032eb329f461` | `c239484a32df5e9d170f777c35e70a0de891cfb26ec60df6405d0ede1c8db54c` | `08687d3d347167d5f77689f6701c1539af47f6fdf6f162fc2bec5118ed9c4d5b` | EQUAL | `TERMINAL_RETIREMENT=0; UNRESOLVED_REFERENCE_GAP=0` | `NONE` | CATALOG_COLUMN 3/3; CATALOG_CONSTRAINT 1/1 | `PHYSICAL_EFFECTS_PRESENT` |
| 25 | `20260713_032015_pessoa_offboarding_preflight_arquivamento_evento.sql` | `144707b97716926a5f94786dd6351335afa598088fab4567a5335dd0f30b61b8` | `0113d2285f6672fe1b1acd7cd4d1403652531436e9b463003dfd8c06ecc6041e` | `6063aafe429a1da02fe18fe5232f1307221aaa711b9a3fe73fe2cc681090da21` | DIFFERENT_OR_PARTIAL | `TERMINAL_RETIREMENT=0; UNRESOLVED_REFERENCE_GAP=0` | `DEFINITION_OR_MISSING_REFERENCE` | CATALOG_COLUMN 9/9; CATALOG_CONSTRAINT 6/6; CATALOG_FUNCTION 0/1; CATALOG_INDEX 3/3; CATALOG_RELATION 0/1; CATALOG_RLS_POLICY 1/1; CATALOG_TRIGGER 1/1 | `PARTIAL_OR_CONFLICTING` |
| 26 | `20260715_204540_msg_idemp1_messages_inbound_provider_id_uidx.sql` | `b1b0f18bbaaa1f6cba6044d137658e326c9eab8ad36e8ec6ebe3e6e322a346b1` | `184a246086bd0d1731da0701a978749f3a077da7b8b6908f5b72fb46a2c0beae` | `a90c3454b92a624919faa0057f5ea63b389f170f2dadda84b8de051fb5606ca3` | EQUAL | `TERMINAL_RETIREMENT=0; UNRESOLVED_REFERENCE_GAP=0` | `NONE` | CATALOG_COLUMN 1/1; CATALOG_INDEX 1/1 | `PHYSICAL_EFFECTS_PRESENT` |
| 27 | `20260715_204541_consolidacao_aberta_unica_por_pessoa.sql` | `29d94dda94755291cde59be232d9d6a23f6eefae3330b207b6c795883bc39f19` | `314823679d7c27faf1838ed0ffb2e57e34daeb5920eea47f46bf7f3597387819` | `c0c9f9a9c252f8e2eb4c7453f3644625668693bfedf85b6f560181a8fe1839bb` | EQUAL | `TERMINAL_RETIREMENT=0; UNRESOLVED_REFERENCE_GAP=0` | `NONE` | CATALOG_INDEX 1/1 | `PHYSICAL_EFFECTS_PRESENT` |
| 28 | `20260720_014832_pessoa_telefone_unico_por_tenant_ativa.sql` | `83278e7bde18b12d021ec74566a747139c2dc53527ba49648a106815dc631062` | `f141d0eb7a822a40d28390b89db68e6d72e550b4f3385c26bb541ae70416567e` | `350a317c410039773ce3f7e2dce290334b7eb6c3d17f14cd9f6218871017bd99` | EQUAL | `TERMINAL_RETIREMENT=0; UNRESOLVED_REFERENCE_GAP=0` | `NONE` | CATALOG_INDEX 1/1 | `PHYSICAL_EFFECTS_PRESENT` |
| 29 | `20260720_191143_consent_records_ator_id_reoptin.sql` | `890e2857e65bd73dcc8efc2406c1109f340ab182660468b8ceb2bd55eb2ad89c` | `f203f39ed3cf33c9c4ac9cc94636fd904f2807096f0e137855e97cd3664f859c` | `5b8c80734ee912e2a20f438791fd0b42121af73fc1bf437dd10c0f8836b991bd` | EQUAL | `TERMINAL_RETIREMENT=0; UNRESOLVED_REFERENCE_GAP=0` | `NONE` | CATALOG_COLUMN 1/1; CATALOG_CONSTRAINT 1/1 | `PHYSICAL_EFFECTS_PRESENT` |
| 30 | `20260730_205332_billing_setup_configuration.sql` | `2238f931f20cccc1ceb8ecdc3cab7a12b3c85a6e1232c95c190f287e306e180c` | `d9b129de43e708b54048043dba5438f56007d3661568772d01a0c19ec8f4da0a` | `2a379fd946cdf9ea69de082a85dd80b8d8a9906ef6cdf7a38cce2b8b7df86f9a` | DIFFERENT_OR_PARTIAL | `TERMINAL_RETIREMENT=0; UNRESOLVED_REFERENCE_GAP=0` | `ACL_ONLY` | CATALOG_COLUMN 55/55; CATALOG_CONSTRAINT 21/21; CATALOG_FUNCTION 1/1; CATALOG_INDEX 12/12; CATALOG_RELATION 1/4; CATALOG_RLS_POLICY 4/4 | `NOT_SCHEMA_DECIDABLE` |
| 31 | `20260731_120000_calendar_oauth_flows_pkce.sql` | `977f9c6193e24a98c17c5e7b74106bca63e62fce64856b61c022c522691d620b` | `3c5ca165f023e1677ffedc853e497740cbfe95dac51445d9341dc4714dddb9a3` | `c4582a7ea9be0fce281a12ee585cd8c3d110f008e9ab2c19400964eebd7dd65a` | EQUAL | `TERMINAL_RETIREMENT=0; UNRESOLVED_REFERENCE_GAP=0` | `NONE` | CATALOG_COLUMN 12/12; CATALOG_CONSTRAINT 5/5; CATALOG_INDEX 3/3; CATALOG_RELATION 1/1; CATALOG_RLS_POLICY 1/1 | `PHYSICAL_EFFECTS_PRESENT` |
| 32 | `20260808_001059_billing_count_active_members.sql` | `e2e04f461e82e68c104fa77b4d34f1cf5d3bb961ee609517f5b1a427654d9e8b` | `bc93b908c7ac1fee24e02f077e9d6900e8007a2cae12ae66a810cc466f574aba` | `9a003d00f5931ddfdcc2d1f11128c65a23f640f657ca3ad496813c5a8a7df80f` | EQUAL | `TERMINAL_RETIREMENT=0; UNRESOLVED_REFERENCE_GAP=0` | `NONE` | CATALOG_FUNCTION 1/1; CATALOG_TRIGGER 1/1 | `NOT_SCHEMA_DECIDABLE` |
| 33 | `20260808_014425_billing_member_plan_label_variants.sql` | `9b84872805ef942add460d53dc3ab7f609413493f7dc0808fb161f81725851e4` | `5e2c5befd6ab097bcd690cd60d0ddc46eacd1f0edef3337bda3204a7ff2976e4` | `b0da187af05a2bb45ff59051f366f2050cfcad97585bb15fea7247366f0d9eee` | NO_STRUCTURAL_TRACE | `NO_STRUCTURAL_TRACE` | `NO_STRUCTURAL_TRACE` | NONE 0/0 | `NOT_SCHEMA_DECIDABLE` |
| 34 | `20260808_023500_billing_reconcile_prepared_member_upgrades.sql` | `9b84872805ef942add460d53dc3ab7f609413493f7dc0808fb161f81725851e4` | `5e2c5befd6ab097bcd690cd60d0ddc46eacd1f0edef3337bda3204a7ff2976e4` | `b0da187af05a2bb45ff59051f366f2050cfcad97585bb15fea7247366f0d9eee` | NO_STRUCTURAL_TRACE | `NO_STRUCTURAL_TRACE` | `NO_STRUCTURAL_TRACE` | NONE 0/0 | `NOT_SCHEMA_DECIDABLE` |
| 35 | `20260822_225752_celula_membro_evento_audit_table.sql` | `203dfaeb0b53e65ac34d05730fc29c74ae9886424dd54708cbd4890f3a10a124` | `25779f538bce7c3ef909c82bd9b35084edd5a251f7c0f189c98acc001dd64ff1` | `7ec739acdede2c47fd807c8e76bdff2538ff4a911ebe0883c9b6aad1d70df047` | DIFFERENT_OR_PARTIAL | `TERMINAL_RETIREMENT=0; UNRESOLVED_REFERENCE_GAP=0` | `ACL_ONLY` | CATALOG_COLUMN 10/10; CATALOG_CONSTRAINT 7/7; CATALOG_FUNCTION 1/1; CATALOG_INDEX 4/4; CATALOG_RELATION 0/1; CATALOG_RLS_POLICY 1/1; CATALOG_TRIGGER 1/1 | `PARTIAL_OR_CONFLICTING` |
| 36 | `20260824_180000_asaas_formal_isolation.sql` | `1caa60f24511284dc03821e65bf6ea7b230044fa810549659e4347109436db3c` | `8846598b6c6c209dbc7ddbe3d4d19fe94d65e801f4269c27a80b55748c2b915d` | `0f1be86fbc1b68313fc529830cfc206e9f5a63b587d8b2765f0ef859d39105fa` | DIFFERENT_OR_PARTIAL | `TERMINAL_RETIREMENT=0; UNRESOLVED_REFERENCE_GAP=0` | `DEFINITION_OR_MISSING_REFERENCE` | CATALOG_COLUMN 0/8; CATALOG_CONSTRAINT 0/5; CATALOG_INDEX 0/9; CATALOG_RELATION 0/1; CATALOG_RLS_POLICY 0/1 | `PARTIAL_OR_CONFLICTING` |
| 37 | `20260826_030508_separar_estado_resposta_agente_de_autor_mensagem.sql` | `31f9ef85fcb2b2a98145dfc5d81dd4e98e29f8fe658940cb4b4b82c9b7410a68` | `d9d6f83d4a907fb8f1f2116b3d04e244451ae7ef5a6b6067a719f7a2dcf542a7` | `e500c4b5aa1b901adf5a1948d69a3d048172d1c75217f6bdf9e13a2ff91fba48` | DIFFERENT_OR_PARTIAL | `TERMINAL_RETIREMENT=0; UNRESOLVED_REFERENCE_GAP=0` | `DEFINITION_OR_MISSING_REFERENCE` | CATALOG_COLUMN 0/1; CATALOG_CONSTRAINT 0/1 | `PARTIAL_OR_CONFLICTING` |
| 38 | `20260826_094317_harden_recovery_artifacts_retention.sql` | `9b84872805ef942add460d53dc3ab7f609413493f7dc0808fb161f81725851e4` | `5e2c5befd6ab097bcd690cd60d0ddc46eacd1f0edef3337bda3204a7ff2976e4` | `b0da187af05a2bb45ff59051f366f2050cfcad97585bb15fea7247366f0d9eee` | NO_STRUCTURAL_TRACE | `NO_STRUCTURAL_TRACE` | `NO_STRUCTURAL_TRACE` | NONE 0/0 | `NOT_SCHEMA_DECIDABLE` |
| 39 | `20260827_175634_d1a_tenant_runtime_integrity.sql` | `7a493ee60908478c28a574e058ce14c26852f3c494d292d38873edce24c6a826` | `c6452517a57ec9eaa40cc6f0524453358f37b0672a7986e618c74799fd20b147` | `d3c38181bfe4a5cfc45ebb8080e5b4f2e2a2121af283504b2ceb2e80c60a9347` | EQUAL | `TERMINAL_RETIREMENT=0; UNRESOLVED_REFERENCE_GAP=0` | `NONE` | CATALOG_CONSTRAINT 13/13; CATALOG_INDEX 14/14 | `PHYSICAL_EFFECTS_PRESENT` |
| 40 | `20260827_230003_d2a_agent_runtime_private_context.sql` | `065b3cc2f1a0e6b6d0bd856f072229daabfcde5087fcb69cd32504d0049db615` | `97619cb41e49eef8ccd274738283ffaf9de5dd6afc04b352d1848a03dae20a04` | `91f3b871f9f64ee78a26424570c32eab9b40e61d74d8b47172bd684f935f82ad` | DIFFERENT_OR_PARTIAL | `TERMINAL_RETIREMENT=0; UNRESOLVED_REFERENCE_GAP=0` | `DEFINITION_OR_MISSING_REFERENCE` | CATALOG_FUNCTION 0/1; CATALOG_SCHEMA 0/1 | `PHYSICAL_EFFECTS_ABSENT` |
| 41 | `20260828_045213_d2b2_consentimento_finalidade_evento.sql` | `34d4ed6c2648ba082d5d357121779e173815dae98c797509a8b746d1b522daf2` | `a53753d0d7dcc2c20c3e0e065bdcc7f37857372e6aabfb2e11e73e6a397636b3` | `aa5af1daeef09d98501ffaac533cca1b0902920ecbc0d585a517bf440a6f8ecd` | DIFFERENT_OR_PARTIAL | `TERMINAL_RETIREMENT=0; UNRESOLVED_REFERENCE_GAP=0` | `DEFINITION_OR_MISSING_REFERENCE` | CATALOG_COLUMN 0/11; CATALOG_CONSTRAINT 0/13; CATALOG_FUNCTION 0/2; CATALOG_INDEX 0/5; CATALOG_RELATION 0/1; CATALOG_RLS_POLICY 0/3; CATALOG_TRIGGER 0/2 | `PHYSICAL_EFFECTS_ABSENT` |
| 42 | `20260828_094914_d2b2b3_purpose_consent_governance_drafts.sql` | `0710de38362371ba781e2293b2cf01d103f4d2773164962f57de1ab0c746bb0a` | `a1f603a4ad9696942bd667499e510adb5e63498db05ffd0964dd81dfd0811650` | `c541c3922706744329d4325cd24ce50323d8773a431b1c274b7776045665c000` | DIFFERENT_OR_PARTIAL | `TERMINAL_RETIREMENT=0; UNRESOLVED_REFERENCE_GAP=0` | `DEFINITION_OR_MISSING_REFERENCE` | CATALOG_COLUMN 0/11; CATALOG_CONSTRAINT 0/10; CATALOG_FUNCTION 0/1; CATALOG_INDEX 0/4; CATALOG_RELATION 0/1; CATALOG_RLS_POLICY 0/1 | `PHYSICAL_EFFECTS_ABSENT` |
| 43 | `20260909_004005_consent_evidence_store_lab.sql` | `4fc9d2bac8cebd6127f3feaedcdff626339fffc036d010c711b903c788199195` | `76d636be7ea3fb5b1b408d48cd65cc9d7d63f6bb3524b3fa280df46b98d668d3` | `b294b62a4bfc9f12cc72d4af66e0422c10923673f96d64e340326cb47f8d5bd5` | DIFFERENT_OR_PARTIAL | `TERMINAL_RETIREMENT=0; UNRESOLVED_REFERENCE_GAP=0` | `DEFINITION_OR_MISSING_REFERENCE` | CATALOG_COLUMN 0/33; CATALOG_CONSTRAINT 0/35; CATALOG_FUNCTION 0/5; CATALOG_INDEX 0/14; CATALOG_RELATION 0/3; CATALOG_RLS_POLICY 0/10; CATALOG_TRIGGER 0/5 | `PHYSICAL_EFFECTS_ABSENT` |
| 44 | `20260910_142830_add_e4b_consent_persistence.sql` | `fdf02b903f4ae431958e0abfe4b5d96fd0bea289f2cf7e7aaabb71c962cacedd` | `97e3e629b60379c9e5fb32323e143843638ced2f67c2f6fb78a27775c6bce46b` | `38a325ab157e418336756005d9aef831dc5faab81904439c4aef4239ea79d355` | DIFFERENT_OR_PARTIAL | `TERMINAL_RETIREMENT=0; UNRESOLVED_REFERENCE_GAP=0` | `DEFINITION_OR_MISSING_REFERENCE` | CATALOG_COLUMN 0/78; CATALOG_CONSTRAINT 0/60; CATALOG_FUNCTION 0/5; CATALOG_INDEX 0/24; CATALOG_RELATION 0/6; CATALOG_RLS_POLICY 0/12; CATALOG_TRIGGER 0/15 | `PHYSICAL_EFFECTS_ABSENT` |

## Resultado limitado

Distribuição derivada: `PHYSICAL_EFFECTS_PRESENT=14`,
`PARTIAL_OR_CONFLICTING=16`, `PHYSICAL_EFFECTS_ABSENT=5` e
`NOT_SCHEMA_DECIDABLE=9`. O item 5 continua com três relações
estruturais na assinatura fonte, mas não fecha as três chaves de relação contra
DEV. O item 30 preserva `REL 6/6` como escopo fonte e permanece não decidível
por DML. O item 39 preserva 13 constraints e 11 índices explícitos com
`pg_temp` excluído. Os itens 40 a 44 ficam ausentes quando suas chaves de
referência não têm correspondência DEV. ACL pública inesperada continua
`UNRESOLVED`, sem nome ou OID.

Natureza das diferenças: `NONE=17`, `ACL_ONLY=10`,
`DEFINITION_OR_MISSING_REFERENCE=10` e
`NO_STRUCTURAL_TRACE=7`. `ACL_ONLY` separa o caso limitado
de `acl_state`, mas não altera a classificação conservadora nem transforma a
diferença local versus plataforma em prova de drift DEV.

Guarda derivada: `PRESENT_WITH_NON_EQUAL=0`. O gerador falha antes de escrever
o anexo se uma linha presente não tiver igualdade `EQUAL`.

Este anexo recomenda somente a continuação documental da estratégia A. A opção
B permanece apenas elegível pela declaração humana já recebida e não está
autorizada.
