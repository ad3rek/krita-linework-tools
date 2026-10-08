KRITA LINEWORK TOOLS
Versão 0.8.1 · Krita 5.2.14 / Linux x86_64 / Qt 5
Integração GPL-3.0-or-later · núcleo OpenToonz BSD-3-Clause

As ferramentas ficam na barra do próprio Krita, em um grupo Linework separado
por uma linha. Os ícones usam a cor do tema e acompanham mudanças de paleta.
Os controles ficam no painel nativo Opções da ferramenta. Não há docker Linework.
O painel contém apenas os ajustes do traço e a aplicação de preset, sem botões
de nova camada, cor, histórico, duplicação ou exportação e sem instruções fixas.
A camada mantém seu ícone próprio e seus traços editáveis no painel Camadas.

Instalação
1. Salve seus desenhos e feche o Krita.
2. Nesta pasta, execute: python3 install.py --enable
3. Reabra o Krita. As ferramentas aparecem na barra de ferramentas.
O instalador guarda a versão anterior e o kritarc em recursos/linework-backups.
O pacote ZIP contém o plugin, a ponte nativa e a definição dos atalhos/ações.
A ponte foi compilada para Krita 5.2.14 do KDE Neon, Qt 5 / Linux x86_64.
Outra versão ou compilação requer validação/recompilação; veja native/BUILD.txt.

Ferramentas
- Linework Brush: escolha um preset no painel Pincéis e desenhe no canvas.
  Ajuste a suavização nativa em Opções da ferramenta > Suavização.
- Linework Curve: clique nos pontos; Enter ou botão direito termina a curva.
- Linework Line: clique nos pontos; Enter ou botão direito termina a linha.
- Linework Edit: selecione/arraste um ou vários pontos e traços. O ponto ativo
  mostra suas alças quadradas; arraste-as para ajustar a tangente. Alt+arrastar
  uma alça move apenas esse lado; arrastar normalmente alinha a alça oposta.
  Duplo clique no traço ou Alt+clique insere um ponto sem deformar a curva.
  Delete remove os pontos selecionados. Ajuste espessura, opacidade e pontas
  dos traços selecionados em Opções da ferramenta.
- Linework Thickness: selecione um ou vários pontos e arraste verticalmente
  ou ajuste Espessura em pixels nas Opções da ferramenta. Guias laterais e
  a indicação junto ao ponto acompanham o diâmetro editado. A pressão capturada
  da caneta permanece independente e disponível para os outros sensores.
- Linework Erase: clique em um traço para excluir o traço inteiro.

Selecionar outra ferramenta do Krita libera sua entrada imediatamente. A captura
Linework depende da ferramenta selecionada; esconder Opções da ferramenta não
interrompe o pincel. Espaço+arrastar, botão central, zoom e Ctrl+clique para
amostrar cor seguem o Krita. Shift+arrastar altera o tamanho em Brush/Curve/Line;
em Edit/Thickness, Shift adiciona ou retira itens da seleção.

Uso
Escolha Linework Brush e um preset do Krita. Cor, tamanho, opacidade e fluxo
atuais são capturados no início de cada traço. O motor nativo produz suas texturas
respeitando a pressão. O preset e suas configurações são guardados por traço;
trocar de pincel não muda os traços anteriores. Os controles de Brush/Curve/Line
configuram o próximo traço. Edit/Thickness ajustam a seleção atual.

Suavização nativa — 0.8.0
Em Linework Brush > Opções da ferramenta > Suavização, escolha:
- Sem suavização: segmentos diretos entre as amostras da caneta/mouse.
- Básica (leve): interpolação Bézier do pincel livre do Krita.
- Ponderada (pesada): filtro nativo por distância, com Finalização,
  Suavizar pressão e Proporcional ao zoom.
- Estabilizador: média nativa das amostras, com distância de atraso,
  Concluir linha e Estabilizar sensores. O círculo no canvas mostra o atraso.

A ponte chama KisToolFreehandHelper/KisSmoothingOptions do próprio Krita 5.2.14;
não substitui os filtros por uma aproximação Python. Os jobs de linha/cúbica
produzidos pelo helper alimentam a prévia incremental. Linhas estacionárias sem
mudança de pressão não criam âncoras duplicadas.

Redução de pontos — 0.8.1
Ao concluir um novo traço do Brush, todos os modos, inclusive Básica, Ponderada
e Estabilizador, reduzem as amostras a curvas Bézier com menos pontos e alças.
A geometria reduzida é reproduzida na aparência final e guardada no .kra.
Não é um novo motor de suavização: é uma compactação depois do filtro nativo.
Os limites geométricos são 0,18 / 0,25 / 0,40 / 0,55 px do documento, respectivamente
em Sem suavização / Básica / Ponderada / Estabilizador; pontas finas usam limites
menores. Cantos marcados continuam como âncoras e curvas fechadas permanecem fechadas.
Pressão e diâmetro independente são ajustados junto com a curva, incluindo seus
controles escalares. A tolerância de pressão é no máximo 0,003 e diminui para
pincéis largos; o perfil de diâmetro independente usa 0,1 px. Picos de pressão e
mudanças de sensores sem deslocamento também são conservados.
A quantidade depende do desenho: detalhes e variações rápidas precisam de mais
pontos. Se o ajuste não reduzir a quantidade ou atingir os limites de trabalho,
o traço original é mantido. A prévia durante o desenho continua incremental.
A redução é automática somente em novos traços do Linework Brush; não modifica
vetores anteriores, curvas colocadas por clique nem a saída do OpenToonz.

As opções usam a configuração compartilhada de suavização do Krita e persistem
entre aberturas. Ao voltar ao Linework Brush, as opções são lidas novamente.
Alterá-las conclui o traço em andamento e configura o próximo traço; vetores
anteriores conservam sua geometria. Suavizar pressão/Estabilizar sensores
também filtra a pressão gravada; o filtro de sensores atua sobre a pressão,
pois o Linework ainda não captura inclinação/rotação física da caneta.
Concluir linha segue o comportamento nativo do estabilizador; desativado,
o final pode permanecer antes do cursor. Esc cancela os timers e o traço.
Salvar durante o desenho conclui o traço antes da captura do documento.

O primeiro traço cria uma camada Linework quando a camada atual não é Linework.
Para começar outra, use Nova camada Linework em Ferramentas > Scripts.
Selecione uma camada Linework em Camadas para recuperar seus traços.
Para mudar o pincel de vetores existentes, use Linework Edit ou Thickness.
Escolha o novo preset no painel Pincéis do Krita. Em Opções da ferramenta >
Pincel, escolha Traços selecionados ou Todos os traços da camada e clique
Trocar pincel. O painel mostra o preset atual do Krita e os pincéis da seleção;
Linha lisa identifica vetores sem preset.
A curva, alças, cor, pressão, espessura, opacidade e pontas são preservadas.
O perfil de espessura já editado é preservado ao trocar presets Pixel/Color Smudge.
Traços anteriores que ainda não têm esse perfil conservam a interpretação original
por pressão até a primeira edição de espessura.
O resultado é preparado um traço por vez, com progresso e Cancelar. Cancelar,
Esc ou trocar de ferramenta/camada preserva os traços anteriores à operação.
Uma troca, inclusive em toda a camada, ocupa uma ação de desfazer/refazer.
Salve em .kra para manter o novo preset e a geometria editável.

Salve em .kra para preservar a edição. Ctrl+Z/Ctrl+Shift+Z no canvas usam o
histórico Linework da sessão; ele é separado do histórico nativo.
O histórico é mantido ao alternar entre as ferramentas Linework da mesma camada.

Durante a edição, só as prévias dos traços afetados aparecem. Suas imagens
originais ficam em cache, carregadas da aparência salva, sem refazer as texturas.
Esc ou trocar de ferramenta/camada cancela o arraste e restaura a aparência exata.
Soltar substitui os traços editados, preservando os demais. A ocultação afeta apenas
o renderizador; salvar durante o arraste encerra a prévia e preserva a última versão confirmada.
O cache de aparências é carregado conforme necessário e limitado a 64 MiB.

Espessura independente — 0.8.0
O desenho continua enviando a pressão original da caneta ao motor nativo do
Krita. Ao editar o diâmetro de um traço nativo pela primeira vez, a contribuição
do sensor Pressão → Tamanho do preset é convertida usando KisCubicCurve do
próprio Krita, incluindo a curva não linear. Tamanho por pressão desativado
corresponde ao tamanho constante do pincel. A geometria de Linha lisa/OpenToonz
conserva exatamente seu polinômio de raio ao criar o perfil independente.

O campo em pixels representa o diâmetro nominal da ponta, antes dos controles
Mínima e Afinar pontas. A espessura base escala esse perfil. A textura, dureza e
formato da ponta podem produzir uma área de tinta diferente do diâmetro nominal.
A edição não altera a pressão gravada nem seus controles: opacidade, fluxo e
outros parâmetros do motor continuam usando o sinal original.

Na reprodução do perfil editado, somente os sensores de Tamanho são substituídos
por um sensor linear de diâmetro. Uma cópia privada do preset usa o canal
Perspective de KisPaintInformation; a pressão usa seu canal próprio. O preset
instalado e as configurações atuais do usuário não são modificados. Funciona
mesmo com Tamanho por pressão desativado, permite ultrapassar a espessura base
e mantém o espaçamento contínuo de um stroke do motor nativo.
O controle direto está disponível para Linha lisa e motores Pixel/Color Smudge;
um motor diferente é recusado antes de aplicar a mudança.

A conversão inicial de traços nativos antigos toma a curva de pressão/tamanho
nas âncoras e nos controles. Uma curva de sensor não linear pode alterar a
interpolação entre as âncoras; variações de Tamanho por outros sensores deixam
de atuar após editar o diâmetro. A aparência antiga permanece salva até editar.
A pressão original, os pontos e as alças de posição permanecem intactos.
O novo perfil e seus controles são salvos em .kra; os esquemas 1–5 continuam
legíveis. O ID interno LineworkPressure é mantido para preservar os atalhos,
mas a ferramenta e as ações aparecem como Linework Thickness — espessura.

Gravação das formas — correção 0.7.1
A importação e substituição dos traços entram em uma espera nativa externa
antes de alterar formas. As esperas internas do Krita drenam os workers sem
executar timers de outros plugins durante a alteração da lista de formas.
Isso corrige o crash de trocar pincel/espessura em camadas grandes com um
observador vetorial ativo, como o editor de poses do AI Diffusion. A preparação
dos pincéis continua em etapas com progresso e Cancelar; a fase final de gravação
aguarda as formas e a projeção completas antes de liberar a interface.
A proteção também cobre desenho, edição, excluir, desfazer/refazer e conversão
raster, pois todas essas operações gravam pela mesma função.
Não modifica outros plugins nem desativa seus timers. Detalhes e regressões
em docs/validation/cc-lineart.json. Reabra o Krita após instalar esta versão para
carregar também a ponte nativa recompilada.

Velocidade
A prévia de Brush é incremental: apenas novos segmentos são enviados aos workers
do Krita. A interface recebe imagens prontas, sem esperar o traço inteiro ou
comprimir PNG a cada movimento. A imagem de trabalho é reaproveitada e descartada
ao sair/fechar o canvas. A curva final suavizada é reproduzida uma vez ao soltar.
Editar pontos refaz a prévia em intervalos limitados; gravar recalcula o traço.
Traços preservados não têm suas imagens serializadas novamente a cada gravação.
Consulte docs/TESTING.md para a medição e seu escopo.

Seleção múltipla de pontos e traços — Edit/Thickness
- Shift+clique adiciona ou retira um ponto/traço da seleção.
- Arraste em uma área vazia para selecionar pontos com um retângulo;
  Shift+arraste acrescenta os pontos à seleção atual. Esc cancela o retângulo.
- Ctrl+A seleciona todos os traços e seus pontos da camada Linework ativa.
- A seleção feita na Seleção de formas do Krita é herdada ao entrar em
  Linework Edit ou Thickness. Cada traço herdado inclui todos os seus pontos.
- Pontos selecionados aparecem em laranja; o painel informa traços e pontos.
  As alças de curva aparecem no ponto ativo. Alternar Edit/Thickness mantém a seleção.

Espessura dos pontos modifica só os pontos selecionados. O campo define o
mesmo diâmetro em pixels, inclusive entre traços com espessuras base diferentes.
O arraste aplica a mesma diferença em pixels às espessuras iniciais; os limites
são 0–2000 px por ponto. Espessura base escala o perfil inteiro de cada traço.
Opacidade, Mínima, pontas e Trocar pincel modificam os traços
que contêm os pontos selecionados. Valores diferentes aparecem como Vários;
preencher o campo aplica o valor ao grupo. Arrastar pontos move todos os pontos
selecionados; arrastar o corpo de traços selecionados move o grupo de traços.
Cada edição em grupo ocupa uma ação de desfazer/refazer. A seleção não cria
histórico e não é gravada no .kra. Na ferramenta Edit, Delete remove os pontos
selecionados; com traços inteiros selecionados, remove esses traços.

Seleção de formas e escala
Mover, redimensionar, girar e espelhar os traços com a Seleção de formas do Krita
atualiza seus pontos e alças, sem bloquear a camada. Ao terminar o gesto, o plugin
reproduz a aparência com o preset salvo e a nova espessura. Voltar para Linework
Edit também sincroniza imediatamente, recuperando a edição do traço.
A forma selecionada conserva o mesmo objeto durante essa atualização; os
comandos nativos de mover/redimensionar continuam podendo desfazer e refazer.
A espessura acompanha a escala uniforme. Para escalas diferentes em X e Y,
usa a média geométrica dos fatores, mantendo uma espessura base circular.
Somente os traços transformados são renderizados novamente. Texturas aleatórias
podem mudar ao reproduzir o preset, como nas demais edições do plugin.
Documentos antigos sem referência de transformação são recuperados pela sua
geometria de origem; novas gravações registram a transformação e o conteúdo SVG.

Vetorização automática de raster
Selecione a camada bitmap ativa e use Ferramentas > Scripts > Vetorizar camada
em Linework. A janela nativa do Krita oferece prévia, comparação com o original,
limiar, remoção de manchas por área, precisão e espessura máxima. Atualize a prévia ao mudar
os ajustes e clique Criar camada Linework. O raster original não é alterado;
por padrão ele é ocultado após criar a nova camada. Desmarque para mantê-lo visível.
Ctrl+Z/Ctrl+Shift+Z na sessão Linework desfaz/refaz a conversão e a ocultação.

Na prévia, use a roda do mouse para ampliar/reduzir sob o cursor e arraste com
o botão esquerdo ou central para navegar. Os botões +/− também controlam o zoom;
Ajustar ou um duplo clique retorna à imagem inteira. O percentual corresponde
à resolução original. O bitmap usa seus pixels originais e o resultado usa os
contornos em cache, sem repetir a extração ao navegar. Trocar a comparação ou
atualizar a prévia conserva o zoom e a região observada.

Use Traços sobre fundo claro para desenhos em papel/fundo branco; Alfa para
linhas sobre transparência, inclusive linhas brancas ou de cor clara.
O modo fundo claro usa o critério original do OpenToonz: máximo de R/G/B,
comparado ao limiar multiplicado pelo alfa. Não usa luminância ponderada.
Precisão vai de 1 a 10; a penalidade do motor é 10 menos a precisão.
Espessura máxima é a largura total; internamente o OpenToonz recebe metade.
As manchas são removidas por área dos contornos, conforme o polygonizer original.
O resultado contém linhas centrais, espessura/pressão, cor por traço e alças Bézier
editáveis. Traços fechados são recuperados com os extremos coincidentes.
A extração e a preparação dos contornos rodam em uma thread de trabalho;
Cancelar não cria camada.
RGBA 8/16 bits e float são lidos com conversão de cor em uma cópia, preservando
os pixels e o espaço de cor originais. A área lida dentro do canvas é limitada
a 32 milhões de pixels. Camadas de pintura e camadas de arquivo são aceitas.

O resultado padrão usa contornos vetoriais lisos. Marque Usar o preset atual do
Krita para reproduzir as curvas com esse pincel; nesse modo a prévia é geométrica,
e a aparência final também depende dos sensores/textura do preset. A aplicação
é feita em etapas e pode ser cancelada antes da criação da camada. Aplicar ao
traço continua disponível em Linework Edit para mudar o pincel depois.

Preservar cor e transparência amostra a aparência depois de calcular as curvas,
sem alterar o algoritmo de detecção. Desmarque para usar preto, como o OpenToonz
ao vetorizar raster RGB com a paleta padrão. Essa opção e os presets do Krita
são adaptações de aparência da integração.

Esta conversão prioriza lineart. Cor e opacidade são estimadas por traço;
fotos, gradientes, preenchimentos e texturas não são reconstruídos como regiões
vetoriais. Interseções viram segmentos independentes unidos pela posição;
editar um segmento não move automaticamente os demais. O histórico é da sessão.
Reimplementação no Krita do mesmo algoritmo Centerline do OpenToonz.
A 0.6.0 porta o código original de polygonize, skeletonize (straight skeleton),
organizeGraphs e conversionToStrokes, além das rotinas originais de cor.
Revisão: 8c5345182b1c3d2ff011a1cf08dad067b6700f08. Os fontes originais e a licença
BSD-3-Clause estão no pacote; a integração não precisa abrir/instalar OpenToonz.
Quadráticas de posição e espessura são elevadas a cúbicas exatamente, sem novo
ajuste ou suavização. Isso preserva a curva central e seu perfil de largura.
Em 16 casos de referência, os controles coincidiram com o núcleo original sem
patches, usando o mesmo raster e os mesmos parâmetros. A renderização dos
contornos, os pincéis e o armazenamento continuam sendo os do Linework/Krita;
o plugin não implementa os preenchimentos/regiões, colormaps TLV ou modo NAA.
Fontes, adaptações e validação: VECTORIZATION.txt e docs/validation/opentoonz-reference.json.


Aparência e limites
Pincéis do Krita são motores raster. Linework mantém uma curva central editável,
com pontos, alças e pressão, e guarda a textura em imagens embutidas na camada vetorial.
A textura tem resolução em pixels; SVG não a torna vetor puro nem preserva os
dados editáveis do plugin. Traços antigos 0.1 continuam lisos até aplicar um preset.
Presets e recursos precisam continuar instalados para reeditar; a aparência salva
permanece visível sem o plugin/preset. Lê documentos das versões anteriores, incluindo 0.7.1.
Os dados novos usam esquema 6: perfil de espessura independente da pressão,
controles do OpenToonz, alças e transformações. Plugins antigos recusam sua
edição; o próprio Krita continua exibindo a aparência salva normalmente.
Linework Line mantém segmentos retos e não exibe alças de curva.

Cada traço pinta sobre transparência. Presets que misturam/amostram outras camadas
não reproduzem essa interação. Borrachas nativas não cortam outros traços; use
Linework Erase. Inclinação, rotação e velocidade real da caneta não são gravadas.
Afinar fim é aplicado à curva final quando o traço termina. Presets pesados podem
continuar lentos; presets aleatórios podem mudar sua textura ao refazer o traço.
Não há importação .sai2, conexão/corte de curvas ou repetição do canvas. Copiar/redimensionar o documento inteiro não transforma os dados centrais.
Alterações manuais do conteúdo SVG continuam protegidas contra substituição.
A mesa física precisa ser validada no seu equipamento.

Análise e código
Ghidra 11.0.3 local analisou referências funcionais do sai2.exe fornecido.
A integração com pincéis usa o motor de pintura do próprio Krita.
Nenhum executável, código decompilado ou recurso proprietário do SAI é incluído.
Código da ponte: linework/native/bridge.cpp. Compilação: linework/native/BUILD.txt.

Desinstalação
Feche o Krita e remova linework.desktop, linework.action e a pasta linework de
recursos/pykrita. A aparência dos documentos .kra continua visível sem o plugin.
