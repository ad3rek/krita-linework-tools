# Testes e reprodução

Ambiente validado: **Linux x86_64, Krita 5.2.14 / Qt 5.15.17 / Python 3.12**. A ponte nativa exige bibliotecas compatíveis. Os testes no canvas são regressões automatizadas do aplicativo real em uma instância isolada; não substituem validação com caneta física.

## Testes CPU

Na raiz do repositório:

```sh
python3 linework/native/build_vectorize.py
python3 -m unittest discover -s tests -v
```

O primeiro comando requer `g++` C++17 e recompila apenas o núcleo de vetorização. A suíte também compila a biblioteca de referência a partir dos fontes originais do OpenToonz. Não exige instalar o aplicativo OpenToonz ou iniciar o Krita.

**51 testes passaram**, incluindo 16 fixtures comparadas com o núcleo original: posição e raio quadráticos coincidem exatamente. [Log da execução publicada](validation/cpu-tests.txt) · [escopo da referência](validation/opentoonz-reference.json).

## Testes no Krita

Requisitos adicionais: Krita 5.2.14 compatível com a ponte, plugin Python/PyQt5 habilitado na instalação do aplicativo, `xvfb-run`, `timeout` e presets padrão do Krita. No Debian/Ubuntu, `xvfb-run` é fornecido por `xvfb` e exige `xauth`.

```sh
python3 tests/gui/run.py cc_lineart
python3 tests/gui/run.py multi_point
python3 tests/gui/run.py smoothing
```

Cada execução cria **configuração, recursos, plugin de teste, diretório temporário e instância Krita separados**. Não utiliza os documentos abertos nem a configuração do Krita do usuário. Os resultados ficam em `work/gui-results/<probe>/`, que é ignorado pelo Git. `--output /caminho` escolhe outro destino.

| Probe | Cobertura |
| --- | --- |
| `cc_lineart` | Bitmap cinza tratado → prévia com zoom → nova camada; troca de preset de todos os traços; diâmetro de todos os pontos; pressão e alças preservadas; histórico; edição; timer observador; salvar/reabrir; fonte intacta. |
| `multi_point` | Seleção nativa herdada, Shift, campos com valores mistos, espessura entre bases diferentes, ocultação durante arraste, Esc, retângulo, exclusão, Ctrl+A e salvar/reabrir. |
| `smoothing` | Eventos Qt de caneta nos quatro filtros nativos, compactação e erro amostrado, pressão, alças, histórico, Esc, atraso, finalização, salvar durante desenho e troca de ferramenta. |

Relatórios publicados: [lineart](validation/cc-lineart.json), [seleção múltipla](validation/multi-point.json), [nova execução de suavização](validation/smoothing.json) e [validação anterior de redução e reabertura em outro processo](validation/point-reduction.json).

Os probes enviam eventos Qt e usam algumas APIs internas do plugin para conferir os dados e o histórico. Não representam uma sessão inteiramente operada por uma pessoa. O observador conta leituras somente **dentro do escopo de mutação efetiva das formas**, após entrar na espera nativa; leituras durante a preparação de pincéis são esperadas e permitidas.

A preparação da imagem é documentada em [ARTWORK.md](ARTWORK.md) e [artwork-source.json](validation/artwork-source.json): recorte, redimensionamento, escala de cinza e níveis. O PNG distribuído já contém esse tratamento. Para refazê-lo a partir do JPEG original, instale Pillow e execute `python3 tests/gui/prepare_fixture.py /caminho/characters-lineart.jpg`. O teste confere que o Krita o abriu no modelo **GRAYA** e que os bytes da camada fonte não mudaram nas operações.

## Limites das medições

Os tempos nos relatórios são medições locais de execuções únicas, com outros processos ativos. Não são garantias de desempenho. O número de amostras do estabilizador depende dos timers; os pontos finais também variam conforme o desenho e a pressão. Os erros de posição/pressão mostrados pelo teste de canvas são amostrados; a compactação tem testes próprios para validar intervalos e casos adversos.

O teste de referência compartilha os adaptadores de tipos do hospedeiro e compara o núcleo original, não o aplicativo OpenToonz completo. A renderização de presets é a do Krita. Funcionalidades de transformação afim têm regressões CPU e validação de desenvolvimento; os três probes desta publicação não exercitam todas as operações da ferramenta nativa de transformação.
