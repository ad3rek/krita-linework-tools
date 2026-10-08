# Krita Linework Tools

Linework editável **dentro do Krita**, inspirado na experiência de camadas de linhas do **Paint Tool SAI**, com vetorização automática baseada no **mesmo núcleo Centerline do OpenToonz**.

Desenhe no canvas com presets nativos, ajuste pontos, alças e espessura e troque o pincel de linhas existentes. As ferramentas ficam na barra do Krita, os ajustes em **Opções da ferramenta** e a camada no painel **Camadas**, com ícone próprio.

**Versão 0.8.1 · build experimental para Linux x86_64, Krita 5.2.14 / Qt 5.15.17.** A ponte usa a ABI interna do Krita. Os binários incluídos precisam dessa versão e de bibliotecas compatíveis; outras builds precisam de recompilação e validação. Windows, macOS e Android ainda não são suportados por este pacote.

![Vetorização da Pepper, com camada e ferramentas no Krita](docs/images/pepper-vectorized.png)

Arte: **David Revoy**, *Characters lineart*, [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Recorte da Pepper, redimensionado e convertido para escala de cinza e tratado com níveis antes dos testes. [Origem e alterações](docs/ARTWORK.md).

## Instalação

1. Baixe e extraia o [pacote 0.8.1](https://github.com/ad3rek/krita-linework-tools/releases/tag/v0.8.1), ou clone este repositório.
2. Salve seus desenhos e feche o Krita.
3. Na pasta extraída, execute `python3 install.py --enable`.
4. Reabra o Krita e escolha **Linework Brush** na barra de ferramentas.

O instalador guarda uma cópia da instalação anterior e da configuração alterada em `linework-backups`, na pasta de recursos do Krita. Também aceita `--resources /caminho/para/recursos`. Para recompilar, consulte [BUILD.txt](linework/native/BUILD.txt).

## O que você pode fazer

| Ferramenta | Uso |
| --- | --- |
| Linework Brush | Desenhar diretamente com um preset do Krita e sua suavização nativa. |
| Linework Curve / Line | Criar curvas ou linhas por cliques; Enter conclui. |
| Linework Edit | Mover pontos e grupos, editar alças, inserir pontos e excluir a seleção. |
| Linework Thickness | Editar o diâmetro em pixels, com guias visuais, inclusive em vários pontos. |
| Linework Erase | Apagar traços inteiros. |

- Suavização **Sem / Básica / Ponderada / Estabilizador**, usando os motores do próprio Krita. Novos traços recebem redução de pontos ao terminar, mantendo cantos e variação de espessura.
- Seleção múltipla com Shift, retângulo e Ctrl+A; a seleção da ferramenta nativa **Seleção de formas** é herdada por Edit/Thickness.
- Troca de preset nos traços selecionados ou em toda a camada, com progresso, cancelamento e uma ação de desfazer.
- Edição com cache da aparência e ocultação do original durante a prévia, evitando a linha duplicada.
- Transformações afins pela Seleção de formas atualizam a geometria e reproduzem o pincel com a escala aplicada.
- Conversão da **camada raster ativa** em uma nova Linework; prévia com zoom e comparação. A camada original é preservada.
- Salvamento dos dados editáveis e da aparência em `.kra`.

Uso completo e limites: [manual](linework/Manual.html) e [referência técnica](README.txt).

## Artigo, capturas e testes

Leia o [artigo em português](docs/ARTICLE.pt-BR.md), com capturas reais do Krita, exemplos, testes funcionais e explicação da implementação.

O pacote inclui [a lineart Creative Commons](examples/pepper-lineart.png), [o resultado editável](examples/pepper-linework.kra) e [um exemplo de suavização e pontos](examples/smoothing-and-points.kra). As imagens particulares usadas durante o desenvolvimento não fazem parte desta publicação.

Os **51 testes CPU** passaram, incluindo comparação exata dos controles de posição e raio em **16 casos sintéticos** com o núcleo original do OpenToonz. Os testes no Krita cobrem desenho, redução, seleção múltipla, espessura, troca de pincel, histórico e salvar/reabrir. [Relatórios e reprodução](docs/TESTING.md).

## Codex, Ghidra, SAI e OpenToonz

Este projeto foi desenvolvido com **OpenAI Codex**, usado na análise, implementação, integração e testes. **Ghidra 11.0.3 foi utilizado para engenharia reversa estática de uma cópia local de Paint Tool SAI 2**, examinando referências funcionais, strings e seus pontos de referência. Essa investigação orientou a reprodução do comportamento de linework. [Método e escopo](docs/ARTICLE.pt-BR.md#codex-ghidra-e-engenharia-reversa).

O algoritmo de detecção é uma **reimplementação/portabilidade no Krita do mesmo algoritmo Centerline do OpenToonz**, com seu código original BSD e adaptadores de integração. A revisão está fixada e os fontes originais, hashes, patches e testes estão disponíveis. [Detalhes](VECTORIZATION.txt) · [procedência](linework/native/opentoonz/ORIGIN.json).

Não é um produto oficial de SAI, OpenToonz ou Krita. Não há executável, recursos proprietários nem código decompilado do SAI no pacote. A reprodução de comportamento não implica equivalência total com o SAI; a correspondência do OpenToonz se refere ao núcleo Centerline RGB/cinza testado, não a todas as funções ou pixels renderizados pelo aplicativo.

## Limites importantes

Pincéis do Krita são raster: a geometria permanece editável, mas a textura é uma imagem embutida na camada vetorial. Presets e recursos precisam estar instalados para reproduzir o traço novamente; a aparência salva continua visível sem o plugin. Espessura independente funciona com Linha lisa e motores Pixel/Color Smudge. Cada traço é renderizado sobre transparência; presets que dependem da tinta de outras camadas não preservam essa interação.

O histórico Linework é próprio da sessão. Não há importação `.sai2`, corte/junção de curvas, regiões de preenchimento do OpenToonz nem repetição de canvas. Redimensionar o documento inteiro não atualiza os dados centrais. A compatibilidade com caneta física ainda precisa ser validada em cada equipamento; os testes automatizados usaram eventos Qt de caneta.

## Licença e créditos

Integração: **GPL-3.0-or-later** ([LICENSE](LICENSE)). Núcleo OpenToonz: **BSD-3-Clause**, preservado em [THIRD-PARTY-NOTICES.txt](THIRD-PARTY-NOTICES.txt) e junto aos fontes. Arte e derivados da Pepper: **CC BY 4.0**, David Revoy, conforme [ARTWORK.md](docs/ARTWORK.md).
