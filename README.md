# 📡 Triagem Inteligente de Chamados de Telecom (Gemini + Vertex AI)

Classifica chamados de uma operadora de telecom por **produto** (fibra, móvel, SIP Trunk, UCaaS, contact center, faturamento), **impacto** e **tipo de cliente**. Depois aplica as **regras de SLA da operação** para definir prioridade (P1 a P4) e fila de atendimento.

## 🎯 Problema que resolve
Na operação de telecom B2B, um chamado de "loja sem internet" e um pedido de "segunda via" chegam pela mesma caixa de entrada. A triagem manual atrasa o atendimento dos casos críticos e estoura SLA. Aqui o Gemini lê o texto livre e a regra de negócio decide a prioridade.

## 🧠 Decisão de arquitetura: IA classifica, regra decide
O modelo só **interpreta o texto** (produto, impacto, se é cliente corporativo, identificadores como circuito e contrato). A **prioridade e o SLA ficam no código**, em uma tabela simples. Assim a decisão que afeta contrato e multa é previsível, auditável e fácil de mudar sem mexer no prompt.

| Impacto | Cliente corporativo | Demais clientes |
|---|---|---|
| Parada total | **P1** (4h) | P2 (8h) |
| Degradação | P2 (8h) | P3 (24h) |
| Dúvida/solicitação | P4 (72h) | P4 (72h) |

## 🏗️ Fluxo
```
chamados.csv ──► Gemini (Vertex AI, saída JSON com schema Pydantic)
                    │  produto · impacto · corporativo · identificadores · resumo
                    ▼
            Regras de SLA (código) ──► prioridade + fila ──► chamados_triados.csv + resumo no terminal
```

## 🧰 Tecnologias
Python · Google Gen AI SDK (`google-genai`) · Gemini no Vertex AI · Pydantic (saída estruturada)

## 🚀 Como rodar
```bash
git clone https://github.com/MoniqueSilva79/triagem-chamados-telecom.git
cd triagem-chamados-telecom
pip install -r requirements.txt

# 1) Sem nuvem: classificador por palavras-chave (linha de base)
python triagem.py data/chamados_exemplo.csv --offline

# 2) Com Gemini no Vertex AI
gcloud auth application-default login
export GOOGLE_CLOUD_PROJECT=seu-projeto
export GOOGLE_CLOUD_LOCATION=us-central1
python triagem.py data/chamados_exemplo.csv
```

## 📊 Exemplo de saída (modo offline)
```
10 chamados triados (regras locais) → chamados_triados.csv

Por prioridade: {'P1': 3, 'P2': 3, 'P3': 1, 'P4': 3}

P1 (atender em até 4h):
  #1001 Fibra / Banda Larga – filial de Campinas sem internet, circuito CAMP-FO-2231...
  #1004 Voz / SIP Trunk – chamadas do PABX não completam, tronco SIP fora do ar...
  #1009 Contact Center – agentes não conseguem logar, operação indisponível...
```

## 💡 Por que ter o modo offline?
- Permite testar o fluxo inteiro sem conta no Google Cloud
- Serve de **linha de base**: rodando os dois modos no mesmo arquivo, dá para medir onde o Gemini acerta mais que as palavras-chave (ex.: "a URA está derrubando os clientes" é degradação, não dúvida)

## 🔒 Cuidados com dados (LGPD)
- Use dados fictícios ou anonimizados nos testes
- O Vertex AI processa os dados no projeto e na região que você escolher

## 🗺️ Próximos passos
- [ ] Ler chamados direto do BigQuery e gravar o resultado de volta
- [ ] Medir acurácia com um conjunto rotulado (Gemini x regras)
- [ ] Expor como API no Cloud Run para integrar com o sistema de tickets

---
Projeto autoral de **Monique da Silva Cruz**, inspirado na rotina de pré-vendas e operação de telecom B2B. Exemplos oficiais do Vertex AI usados como referência de estudo: [GoogleCloudPlatform/vertex-ai-samples](https://github.com/GoogleCloudPlatform/vertex-ai-samples).
