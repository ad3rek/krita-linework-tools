# Krita Linework Tools: linhas editáveis com pincéis do Krita

O **Krita Linework Tools** traz para o Krita uma experiência inspirada nas camadas Linework do **Paint Tool SAI**: desenhar uma linha com o pincel, conservar sua curva central e depois ajustar pontos, alças, espessura e preset. A conversão de bitmap usa uma portabilidade do **mesmo algoritmo Centerline do OpenToonz**.

O desenvolvimento foi feito com **OpenAI Codex**, incluindo análise, código, integração e testes. **Ghidra 11.0.3** foi usado para engenharia reversa estática do Paint Tool SAI 2, como referência de comportamento. Mais abaixo descrevemos precisamente o alcance dessa análise e a origem do vetorizador.

Esta publicação corresponde à **0.8.1**, testada em **Krita 5.2.14, Linux x86_64, Qt 5.15.17 e Python 3.12**. É uma build experimental que depende da ABI interna dessa versão do Krita. Não basta copiar os binários para outra versão ou para Android; esses ambientes ainda precisam de recompilação e validação.

## Tudo no próprio Krita

As seis ferramentas aparecem na barra do Krita, com ícones que acompanham o tema e uma linha separando o grupo. Seus controles ficam em **Opções da ferramenta**. A camada Linework fica no painel **Camadas**, com um ícone próprio, e continua sendo uma camada vetorial do documento.

![Lineart vetorizada na interface real do Krita](images/pepper-vectorized.png)

*Captura real do Krita 5.2.14: a conversão criou uma camada Linework editável e preservou a camada raster, ocultada. Arte: David Revoy, “Characters lineart”, Pepper&Carrot, CC BY 4.0; recorte, redução e conversão para cinza. [Créditos completos](ARTWORK.md).*

Escolha **Linework Brush**, selecione um preset no painel de pincéis do Krita e desenhe diretamente no canvas. Cor, tamanho, opacidade, fluxo e preset são capturados no início do traço. Curve e Line permitem colocar pontos por cliques; Enter termina a linha. Edit mostra pontos e alças; Thickness edita o diâmetro; Erase exclui traços inteiros.

A integração usa os motores de pintura nativos do Krita para reproduzir as curvas. A geometria é editável, mas a textura do pincel continua sendo raster: ela fica embutida na camada junto dos dados da linha. Salvar em `.kra` preserva ambos. Presets e recursos devem continuar disponíveis para renderizar novamente, embora a aparência salva possa ser vista sem o plugin.

## Converter uma lineart em linhas editáveis

Para a demonstração escolhemos a Pepper, de **Pepper&Carrot**, com desenho de David Revoy e licença **CC BY 4.0**. Usamos um recorte da imagem original, redimensionado para **833 × 1280 pixels** e convertido para **escala de cinza de 8 bits** e tratado com níveis de entrada **128–220**, gama **1,0** e saída **0–255**, antes de abri-lo no Krita. Isso deixa as linhas pretas e o fundo branco, preservando a gradação das bordas. A imagem particular usada durante o desenvolvimento e o primeiro exemplo de gato ficaram fora da publicação.

Selecione a camada bitmap e abra **Ferramentas → Scripts → Vetorizar camada em Linework**. O diálogo oferece limiar, remoção de manchas, precisão, largura máxima, comparação e zoom. O botão de criação produz uma nova camada; a fonte fica intacta e pode ser ocultada.

![Prévia comparando o bitmap em cinza com a linha central](images/pepper-vectorize-preview.png)

*Original à esquerda e resultado à direita. Arte de David Revoy, CC BY 4.0, com as alterações de preparação indicadas acima.*

Com limiar **170**, remoção de manchas abaixo de **12 px²**, precisão **9,5** e largura máxima **200 px**, o teste gerou **743 traços e 2.206 âncoras**. A prévia informou **0,25 s** para a extração e preparação; isso não inclui trocar presets, reproduzir todos os pincéis nem gravar a camada. Os pixels da fonte permaneceram iguais antes e depois de converter, editar e salvar.

O vetorizador extrai as linhas centrais e seus raios. O preenchimento cinza do desenho não é reconstruído. A escolha do limiar e do tamanho da imagem influencia quantos detalhes e pequenos segmentos são detectados; uma lineart esboçada pode exigir limpeza posterior.

## Espessura, pontos e mudança de pincel

Em **Linework Edit**, arraste um ponto ou um grupo. O ponto ativo mostra alças; Alt permite mover uma alça sem alinhar a oposta. Duplo clique no traço ou Alt+clique insere um ponto preservando a curva por subdivisão. Delete remove a seleção.

Shift adiciona ou retira itens; um retângulo seleciona pontos; Ctrl+A seleciona tudo. Uma seleção feita com **Seleção de formas** também é herdada ao entrar em Edit ou Thickness. Isso permite alterar a espessura de pontos em várias linhas de uma vez.

![Preset nativo e indicadores da espessura nos vetores da Pepper](images/pepper-native-thickness.png)

*Depois de aplicar o preset nativo `u) Pixel Art` aos 743 traços e definir seus diâmetros em 4 px. A captura mostra três pontos selecionados, guias de largura e o valor no canvas. Arte de David Revoy, CC BY 4.0, adaptada em Linework.*

O campo de espessura representa o **diâmetro nominal em pixels**. A pressão da caneta permanece separada, para continuar alimentando opacidade e outros sensores. Na primeira edição de largura de um traço nativo, a contribuição Pressão → Tamanho é convertida usando a curva do próprio Krita. O controle direto de diâmetro cobre Linha lisa e motores Pixel/Color Smudge; formato e textura da ponta ainda podem produzir tinta diferente do diâmetro nominal.

Para trocar o pincel de linhas existentes, escolha o preset no Krita, defina o alcance **Traços selecionados** ou **Todos os traços da camada** e clique **Trocar pincel** em Opções da ferramenta. A operação prepara os traços em etapas, oferece cancelamento e ocupa uma ação no histórico Linework. O preset instalado do usuário não é alterado.

Durante uma edição, a aparência original dos traços afetados fica oculta do renderizador e disponível em cache. A prévia ocupa seu lugar. Esc restaura a versão confirmada; soltar reproduz e grava a alteração. Os testes verificam que duas linhas selecionadas ficam ocultas durante o arraste e que Esc restaura seus dados e imagens.

![Seleção múltipla e edição de diâmetros em curvas sintéticas](images/multi-point-thickness.png)

*Curvas sintéticas criadas para o teste: seleção de pontos em mais de um traço, espessura independente e controles no painel nativo.*

Mover, escalar, girar ou espelhar pelas ferramentas nativas atualiza os pontos e alças e reproduz o preset com a transformação aplicada. Escala uniforme afeta a espessura; escala não uniforme usa a média geométrica dos fatores para manter uma largura circular. Transformar o documento inteiro ainda não atualiza esses metadados.

## Suavização nativa com menos pontos

O Brush usa **KisToolFreehandHelper** e **KisSmoothingOptions**, do próprio Krita. Os quatro modos são Sem suavização, Básica, Ponderada e Estabilizador. Distância, finalização, suavização de pressão e atraso ficam nas Opções da ferramenta e usam a configuração compartilhada do Krita.

![Controles de suavização nativa no Linework Brush](images/smoothing-options.png)

Depois que um novo traço termina, a versão 0.8.1 compacta a curva em Béziers com menos pontos. A compactação ocorre **depois** do filtro nativo e conserva os cantos e as variações de pressão/espessura dentro das tolerâncias configuradas. Traços antigos e vetores importados não são compactados automaticamente.

![Pontos reduzidos e alças em curvas de teste](images/reduced-points.png)

*Exemplo salvo da validação de 0.8.1, com geometria reduzida reaberta no editor.*

Em uma nova execução automatizada no canvas, com eventos Qt de caneta e 100 movimentos por traço, obtivemos:

| Modo | Pontos antes → depois | Maior erro de posição amostrado | Tempo de compactação |
| --- | --- | --- | --- |
| Sem suavização | 101 → 11 | 0,120 px | 22,1 ms |
| Básica | 101 → 5 | 0,121 px | 75,9 ms |
| Ponderada | 101 → 12 | 0,196 px | 54,1 ms |
| Estabilizador | 1.233 → 6 | 0,278 px | 167,7 ms |

Esses valores descrevem esse desenho e essa execução. A temporização do estabilizador afeta a quantidade de amostras; outras curvas precisam de outras quantidades. O teste anterior salvo em `smoothing-and-points.kra` produziu 10/6/12/5 âncoras. Ambos os resultados estão registrados. Não usamos uma caneta física nos testes automatizados.

## Testes funcionais e seus limites

Os **51 testes CPU passaram** na pasta publicada. Eles cobrem modelo, seleção, inserção, serialização, fingerprints, transformações, compactação e vetorização. O teste diferencial compila os fontes originais do OpenToonz e verifica igualdade exata dos controles de posição e raio em **16 fixtures sintéticas**.

| Operação no Krita | Verificação |
| --- | --- |
| Bitmap cinza → Linework | Nova camada nativa, 743 traços / 2.206 pontos, fonte intacta. |
| Zoom da prévia | Ampliar e ajustar funcionam usando os dados em cache. |
| Trocar o preset da camada inteira | Todos os traços recebem Pixel Art; geometria preservada; desfazer/refazer restauram a operação. |
| Alterar todos os diâmetros | Todos os pontos chegam a 4 px; pressão original e alças ficam iguais; uma ação de histórico. |
| Editar um ponto importado | O traço é reproduzido e os dados voltam corretamente com desfazer/refazer. |
| Salvar/reabrir | Dados editáveis iguais e raster original com os mesmos bytes. |
| Outro plugin lendo formas | Timer observador continua ativo na preparação; nenhuma leitura ocorre durante a mutação protegida da cena. |
| Seleção e edição em grupo | Herança da Seleção de formas, Shift, retângulo, arraste, indicadores, exclusão e histórico. |
| Brush e suavização | Quatro motores nativos, pressão, alças, redução, Esc, atraso, troca de ferramenta e salvar durante um traço. |

Na Pepper em cinza, a troca de preset de toda a camada levou **36,1 s** e a alteração de todos os diâmetros, **81,8 s**, incluindo renderização e gravação. São medições locais de uma execução, com outros processos ativos, não um benchmark controlado. Camadas grandes e presets pesados ainda podem demorar; progresso e cancelamento ajudam na fase de preparação.

A proteção contra a corrida de gravação mantém uma espera nativa externa enquanto os workers do Krita alteram as formas. Assim, esperas internas não executam timers que tentem ler formas em alteração. O teste usa um observador de formas para reproduzir esse padrão de concorrência; não equivale a certificar todas as versões de plugins de terceiros.

[TESTING.md](TESTING.md) contém comandos e escopo; os [relatórios JSON](validation/) e os scripts estão no repositório. As capturas são do aplicativo real, sem montagem de interface.

## O mesmo algoritmo Centerline do OpenToonz

Esta é uma **reimplementação/portabilidade do mesmo algoritmo de vetorização Centerline do OpenToonz no Krita**, baseada diretamente no código original BSD-3-Clause da revisão [`8c5345182b1c3d2ff011a1cf08dad067b6700f08`](https://github.com/opentoonz/opentoonz/tree/8c5345182b1c3d2ff011a1cf08dad067b6700f08).

O fluxo porta polygonize, skeletonize por straight skeleton, organização do grafo, ajuste de traços e rotinas de cor. Os controles quadráticos de posição e raio são elevados a cúbicos exatamente, para o modelo do Linework. Os arquivos originais, seus hashes e os patches de integração estão documentados em [ORIGIN.json](../linework/native/opentoonz/ORIGIN.json) e [VECTORIZATION.txt](../VECTORIZATION.txt).

O caminho disponível é Centerline para raster RGB/cinza. Adaptadores fornecem os tipos e o armazenamento do aplicativo hospedeiro. Não foram implementados colormaps TLV, modo NAA ou regiões preenchidas. A renderização final usa Linework/Krita, portanto a igualdade do núcleo testado não promete a mesma imagem pixel a pixel do aplicativo OpenToonz completo.

## Codex, Ghidra e engenharia reversa

**OpenAI Codex foi utilizado no desenvolvimento deste plugin. Ghidra 11.0.3 foi utilizado para engenharia reversa estática de Paint Tool SAI 2**, a partir de uma cópia local do executável fornecida pelo usuário.

Os registros dessa análise mostram a importação PE x86-64 concluída, 7.038 funções identificadas pela análise automática e um inventário de 59 strings relacionadas às funções investigadas, com suas referências. O [script de inspeção criado para o projeto](InspectLinework.java) percorre strings definidas e referências para ajudar a localizar recursos relacionados a linework, curvas e pressão.

Essa evidência sustenta a investigação de funcionalidades e a inspiração comportamental. Ela **não demonstra uma cópia do algoritmo interno de pincel ou do formato de arquivo do SAI**. A implementação usa o motor do Krita, geometria do Linework e o código aberto do OpenToonz. Não distribuímos o executável do SAI, o banco de análise do Ghidra, recursos proprietários nem código decompilado do SAI.

## Instalação, licença e continuidade

Baixe a [versão 0.8.1](https://github.com/ad3rek/krita-linework-tools/releases/tag/v0.8.1), confira a compatibilidade, feche o Krita e execute `python3 install.py --enable` na pasta extraída. O instalador conserva backups da instalação anterior. Leia o [README](../README.md) e o [manual](../linework/Manual.html) para uso e desinstalação.

A integração é **GPL-3.0-or-later**; os fontes do OpenToonz preservam **BSD-3-Clause**. A arte da Pepper e suas adaptações mantêm **CC BY 4.0**, com atribuição a David Revoy e indicação das alterações. O projeto é independente e não implica endosso dos autores ou dos aplicativos usados como referência.
