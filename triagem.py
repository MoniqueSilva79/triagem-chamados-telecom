"""Triagem automática de chamados de telecom com Gemini (Vertex AI).

Lê um CSV de chamados, classifica cada um por produto, prioridade e fila de
atendimento, aplica as regras de SLA da operação e gera um relatório.

Uso:
    python triagem.py data/chamados_exemplo.csv            # usa o Gemini no Vertex AI
    python triagem.py data/chamados_exemplo.csv --offline  # usa regras locais (sem nuvem)
"""
import argparse
import csv
import os
import re
from collections import Counter
from enum import Enum

from pydantic import BaseModel, Field


class Produto(str, Enum):
    FIBRA = "Fibra / Banda Larga"
    MOVEL = "Móvel"
    SIP = "Voz / SIP Trunk"
    UCAAS = "UCaaS / Teams Phone"
    CCAAS = "Contact Center"
    FATURA = "Faturamento"
    OUTROS = "Outros"


class Impacto(str, Enum):
    TOTAL = "parada total"
    PARCIAL = "degradação"
    DUVIDA = "dúvida ou solicitação"


class Classificacao(BaseModel):
    produto: Produto
    impacto: Impacto
    cliente_corporativo: bool = Field(description="True se o texto indica empresa, filial ou contrato B2B")
    identificadores: list[str] = Field(description="Circuitos, números de linha, contratos ou protocolos citados")
    resumo: str = Field(description="Resumo do problema em até 20 palavras")


# Regras de negócio da operação: ficam no código, não no modelo,
# para que a prioridade seja sempre previsível e auditável.
FILAS = {
    Produto.FIBRA: "N2 Rede Fixa",
    Produto.MOVEL: "N2 Rede Móvel",
    Produto.SIP: "N2 Voz Corporativa",
    Produto.UCAAS: "N2 Colaboração",
    Produto.CCAAS: "N2 Contact Center",
    Produto.FATURA: "Backoffice Financeiro",
    Produto.OUTROS: "N1 Atendimento",
}
SLA_HORAS = {"P1": 4, "P2": 8, "P3": 24, "P4": 72}


def prioridade(c: Classificacao) -> str:
    if c.impacto == Impacto.TOTAL:
        return "P1" if c.cliente_corporativo else "P2"
    if c.impacto == Impacto.PARCIAL:
        return "P2" if c.cliente_corporativo else "P3"
    return "P4"


PROMPT = """Você classifica chamados de uma operadora de telecom brasileira.
Leia o chamado e responda somente com o JSON pedido.
- "parada total": serviço indisponível (sem sinal, sem internet, sem completar chamadas).
- "degradação": funciona com falhas (lentidão, quedas, áudio ruim, fila travando).
- "dúvida ou solicitação": dúvidas, pedidos comerciais, segunda via, mudança de plano.
Chamado (canal {canal}): \"\"\"{texto}\"\"\""""


_cliente = None


def classificar_gemini(texto: str, canal: str) -> Classificacao:
    from google import genai
    from google.genai import types

    global _cliente
    if _cliente is None:
        _cliente = genai.Client(
            vertexai=True,
            project=os.environ["GOOGLE_CLOUD_PROJECT"],
            location=os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1"),
        )
    resposta = _cliente.models.generate_content(
        model=os.environ.get("MODELO", "gemini-2.5-flash"),
        contents=PROMPT.format(texto=texto, canal=canal),
        config=types.GenerateContentConfig(
            temperature=0,
            response_mime_type="application/json",
            response_schema=Classificacao,
        ),
    )
    return Classificacao.model_validate_json(resposta.text)


# Classificador por palavras-chave: permite rodar e testar sem conta no Google Cloud
# e serve de linha de base para comparar com o Gemini.
PALAVRAS = [
    (Produto.CCAAS, r"\bura\b|contact center|agentes?|fila de atendimento|discador"),
    (Produto.UCAAS, r"teams|ucaas|webex|ramal virtual"),
    (Produto.SIP, r"sip|tronco|pabx|e1\b|chamadas? (não|nao) complet"),
    (Produto.MOVEL, r"chip|celular|4g|5g|roaming|linha m[oó]vel|sem sinal"),
    (Produto.FATURA, r"fatura|boleto|cobran[cç]a|segunda via|valor"),
    (Produto.FIBRA, r"fibra|internet|banda larga|link|wi-?fi|roteador|ont\b"),
]


def classificar_offline(texto: str, canal: str) -> Classificacao:
    t = texto.lower()
    produto = next((p for p, rx in PALAVRAS if re.search(rx, t)), Produto.OUTROS)
    if re.search(r"parad|fora do ar|sem (sinal|internet|acesso)|n[aã]o (funciona|completa)|caiu tud|indispon", t):
        impacto = Impacto.TOTAL
    elif re.search(r"lent|oscila|cai[ un]|picot|ruim|intermit|trav|derrub", t):
        impacto = Impacto.PARCIAL
    else:
        impacto = Impacto.DUVIDA
    corporativo = bool(re.search(r"empresa|filia|loja|cnpj|contrato|ltda|s\.a\.|matriz|unidade", t))
    ids = re.findall(r"(?:circuito|contrato|protocolo)\s*[:#]?\s*([\w-]+)|(\(?\d{2}\)?\s?9?\d{4}-?\d{4})", texto, re.IGNORECASE)
    identificadores = [a or b for a, b in ids]
    resumo = " ".join(texto.split()[:20])
    return Classificacao(produto=produto, impacto=impacto, cliente_corporativo=corporativo,
                         identificadores=identificadores, resumo=resumo)


def main():
    parser = argparse.ArgumentParser(description="Triagem de chamados de telecom")
    parser.add_argument("arquivo", help="CSV com as colunas id, canal, texto")
    parser.add_argument("--offline", action="store_true", help="usa regras locais em vez do Gemini")
    parser.add_argument("--saida", default="chamados_triados.csv")
    args = parser.parse_args()

    classificar = classificar_offline if args.offline else classificar_gemini
    with open(args.arquivo, encoding="utf-8") as f:
        chamados = list(csv.DictReader(f))

    linhas = []
    for ch in chamados:
        c = classificar(ch["texto"], ch.get("canal", "não informado"))
        p = prioridade(c)
        linhas.append({
            "id": ch["id"],
            "produto": c.produto.value,
            "impacto": c.impacto.value,
            "corporativo": "sim" if c.cliente_corporativo else "não",
            "prioridade": p,
            "sla_horas": SLA_HORAS[p],
            "fila": FILAS[c.produto],
            "identificadores": "; ".join(c.identificadores),
            "resumo": c.resumo,
        })

    with open(args.saida, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(linhas[0]))
        writer.writeheader()
        writer.writerows(linhas)

    print(f"{len(linhas)} chamados triados ({'regras locais' if args.offline else 'Gemini'}) → {args.saida}\n")
    print("Por prioridade:", dict(sorted(Counter(l["prioridade"] for l in linhas).items())))
    print("Por fila:")
    for fila, qtd in Counter(l["fila"] for l in linhas).most_common():
        print(f"  {qtd:>3}  {fila}")
    urgentes = [l for l in linhas if l["prioridade"] == "P1"]
    if urgentes:
        print("\nP1 (atender em até 4h):")
        for l in urgentes:
            print(f"  #{l['id']} {l['produto']} – {l['resumo']}")


if __name__ == "__main__":
    main()
