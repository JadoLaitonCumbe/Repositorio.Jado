# GEmpresa-JLC — Plano de arquitetura para escala nacional (Moçambique)

## 1. Objetivo e âmbito

Preparar a plataforma para servir empresas, instituições e grupos empresariais nas 11 províncias de Moçambique, com múltiplas filiais por empresa, isolamento rigoroso entre organizações e acesso web/Desktop. A arquitetura abaixo é um alvo técnico. Não significa que a infraestrutura nacional, alta disponibilidade ou capacidade de milhares de sessões já esteja instalada ou validada.

## 2. Modelo de administração

- **Administrador Geral GEmpresa-JLC:** aprova, suspende e bloqueia empresas; acompanha indicadores agregados; pesquisa o diretório nacional; consulta auditoria da plataforma.
- **Proprietário:** controla a organização, utilizadores, departamentos, filiais, licenças e permissões.
- **Diretor/Gerente:** acompanha metas, projetos, indicadores e operações autorizadas.
- **Financeiro:** caixa, bancos, contas a pagar/receber, movimentos e relatórios financeiros.
- **RH:** funcionários, departamentos, assiduidade, contratos e salários (módulo ainda por desenvolver).
- **Vendas/Marketing:** clientes, oportunidades, campanhas e vendas (módulos ainda por desenvolver).
- **Compras/Stock:** fornecedores, encomendas, armazéns e inventário (módulos ainda por desenvolver).
- **Funcionário:** acesso mínimo, apenas aos módulos autorizados.

A autorização é aplicada no servidor. A interface nunca é a única barreira de segurança. Os papéis têm permissões padrão e o proprietário pode criar exceções por permissão, sem poder remover os privilégios fundamentais de `owner` e `admin` nesta versão.

## 3. Geografia e estrutura multiempresa

- Diretório nacional de empresas com província, distrito, setor e dimensão.
- Cada empresa é um tenant independente, identificado por `company_id`.
- Uma empresa pode ter várias filiais, cada uma com província, distrito e endereço.
- Todas as consultas de dados empresariais devem filtrar pelo tenant no servidor.
- A administração geral vê dados de cadastro e métricas agregadas; não deve aceder por defeito a documentos financeiros privados de cada empresa.
- A expansão para grupos com várias empresas exige uma camada futura de `tenant_group_id`, com consolidação explicitamente autorizada.

## 4. Arquitetura nacional alvo

```text
Utilizadores Web / Desktop / Mobile
                 |
        DNS + WAF + TLS + CDN
                 |
       API Gateway / Load Balancer
                 |
     API FastAPI horizontal (N instâncias)
        |          |           |
   PostgreSQL    Redis     Fila de tarefas
   HA + réplica   Cluster   Workers assíncronos
        |          |           |
   Backups PITR  Cache/limites  Email/SMS/PDF/IA
        |
   Object Storage cifrado (documentos e backups)
        |
 Observabilidade: métricas, logs, traces e alertas
```

### Componentes obrigatórios antes de produção nacional

1. Migrar o armazenamento ativo de SQLite para PostgreSQL, com migrações versionadas, pool de conexões, constraints e índices por tenant.
2. Usar Redis partilhado para rate limiting, sessões/cache quando aplicável e coordenação de tarefas.
3. Usar uma fila de tarefas (Celery/RQ ou equivalente) para relatórios pesados, notificações, importações, reconciliação e sincronização em lote.
4. Executar várias instâncias stateless da API atrás de load balancer.
5. Guardar anexos e documentos em object storage, não no disco efémero dos servidores.
6. Backups cifrados, cópias fora do local primário, PITR e testes regulares de restauração.
7. Monitorização centralizada com alertas de latência, erros, saturação, filas, falhas de sincronização e uso de recursos.
8. Plano de recuperação de desastre com local secundário e procedimentos testados.

## 5. Disponibilidade e recuperação — objetivos iniciais propostos

| Indicador | Objetivo inicial a validar |
|---|---:|
| Disponibilidade mensal | 99,9% |
| RPO (perda máxima de dados) | 15 minutos |
| RTO (tempo de recuperação) | 4 horas |
| Retenção de auditoria | Definida por política e legislação aplicável |
| Teste de restauração | Trimestral, no mínimo |

Estes são objetivos de desenho, não garantias atuais.

## 6. Segurança e conformidade

- MFA obrigatório para administradores gerais e contas privilegiadas.
- RBAC com permissões verificadas no servidor e princípio do menor privilégio.
- Isolamento multi-tenant e testes negativos entre empresas/filiais.
- TLS em trânsito, cifragem em repouso e gestão/rotação de segredos.
- Sessões curtas para perfis privilegiados, revogação e registo de eventos.
- Auditoria imutável ou protegida contra alteração por operadores comuns.
- Políticas de retenção, exportação e eliminação de dados.
- Avaliação jurídica e contabilística local antes de usar o ERP para obrigações fiscais, laborais, faturação ou contabilidade oficial em Moçambique.

## 7. Plano de testes de capacidade

Não declarar capacidade nacional com base em testes ao endpoint `/health`. O plano deve evoluir por fases:

1. Testes de unidade e integração por módulo e por papel.
2. Testes multi-tenant com dados sintéticos de milhares de empresas.
3. Carga realista: login, dashboard, movimentos financeiros, vendas, stock, relatórios e sincronização Desktop.
4. Testes de pico, soak (24–72h), falhas de Redis, failover de PostgreSQL e perda temporária de rede.
5. Testes de recuperação a partir de backups.
6. Aumentar a carga gradualmente e dimensionar com métricas reais; definir metas de concorrência após levantamento de uso esperado.

## 8. Estado da implementação nesta entrega

### Implementado nesta entrega

- Painel web do Administrador Geral em `/admin`.
- Login administrativo por formulário com CSRF e sessão renovada.
- Aprovação, suspensão e bloqueio de empresas no painel.
- Indicadores globais e diretório com pesquisa/paginação na API administrativa.
- Cadastro de localização nacional: província, distrito, setor e dimensão.
- Cadastro de filiais por empresa e listagem isolada por tenant.
- Papéis adicionais e permissões configuráveis por empresa; verificações aplicadas em módulos estratégicos, financeiros, RH, stock, CRM, projetos e fornecedores.
- Rate limiting distribuído via Redis quando `REDIS_URL` está configurado; em produção, a ausência de Redis bloqueia a operação de rate limiting.
- Testes de regressão para painel, diretório nacional, filiais, RBAC e isolamento.

### Ainda não implementado / bloqueador para escala nacional

- O adaptador ativo de persistência continua SQLite. O SQL PostgreSQL em `migrations/postgresql/` é uma base de migração, não uma ligação ativa da aplicação.
- Redis está integrado para rate limiting, mas não para sessões distribuídas/cache geral.
- Não há ainda workers Celery em produção nem pipeline assíncrono completo.
- MFA/TOTP para Administrador Geral ainda não está concluído.
- Não há HA, failover, CDN/WAF, object storage, monitorização Prometheus/Grafana ou disaster recovery configurados nesta entrega.
- Os módulos ERP de RH/payroll, contabilidade formal, compras, vendas/faturação, marketing, gestão jurídica e IA continuam em desenvolvimento.

**Conclusão:** esta versão melhora o plano de controlo nacional e as fundações multiempresa, mas não deve ser exposta como ERP nacional de produção antes de concluir os bloqueadores acima e realizar auditoria independente.
