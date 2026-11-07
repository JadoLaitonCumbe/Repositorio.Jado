# GEmpresa-JLC — Release 1.0.0

**Produto da JLC-tech**

Esta versão consolida a base Hybrid National R3 como o produto oficial **GEmpresa-JLC**.

## Melhorias desta entrega

- Rebranding completo de AlphaTech-JLC para GEmpresa-JLC.
- Identidade oficial JLC-tech aplicada à interface web, cliente desktop, documentação e infraestrutura.
- Metadados de produto centralizados em `app/product.py`.
- Endpoint `/api/product` para identificação da versão, marca e produto.
- Health check identificado pelo produto e marca.
- Cliente Desktop passa a usar armazenamento local e namespace de credenciais próprios do GEmpresa-JLC.
- Mantida a arquitetura multiempresa, RBAC, diretório nacional, filiais, auditoria e sincronização híbrida da base R3.
- Mantida a separação entre desenvolvimento SQLite e a camada de infraestrutura PostgreSQL/Redis preparada para evolução de produção.

## Identidade

**GEmpresa-JLC**  
**Produto da JLC-tech**  
*Gestão empresarial inteligente, integrada e preparada para Moçambique.*

## Próxima fase recomendada

A próxima versão deve priorizar PostgreSQL como backend operacional, Redis para estado distribuído, MFA do Administrador Geral, observabilidade, backups PITR, dashboards por perfil e sincronização offline/online completa para os módulos ERP.
