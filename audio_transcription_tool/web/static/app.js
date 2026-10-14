"use strict";

const $ = (id) => document.getElementById(id);
let estado = null;
let audios = [];
let consulta = null;

// --- Utilitários ------------------------------------------------------------

async function api(caminho, opcoes = {}) {
  const resposta = await fetch(caminho, {
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    ...opcoes,
  });
  if (!resposta.ok) {
    let detalhe = resposta.statusText;
    try { detalhe = (await resposta.json()).detail || detalhe; } catch (_) { /* sem JSON */ }
    const erro = new Error(detalhe);
    erro.status = resposta.status;
    throw erro;
  }
  const tipo = resposta.headers.get("content-type") || "";
  return tipo.includes("application/json") ? resposta.json() : resposta.text();
}

function duracao(segundos) {
  if (segundos == null) return "—";
  const s = Math.round(segundos);
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), r = s % 60;
  const dois = (n) => String(n).padStart(2, "0");
  return h ? `${h}:${dois(m)}:${dois(r)}` : `${m}:${dois(r)}`;
}

function duracaoTexto(segundos) {
  if (segundos == null) return "";
  const min = Math.round(segundos / 60);
  if (min < 1) return "menos de 1 minuto";
  if (min < 60) return `cerca de ${min} min`;
  const h = Math.floor(min / 60), m = min % 60;
  return `cerca de ${h} h${m ? ` ${m} min` : ""}`;
}

function tamanho(bytes) {
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  if (bytes < 1024 ** 3) return `${(bytes / 1024 / 1024).toFixed(1).replace(".", ",")} MB`;
  return `${(bytes / 1024 ** 3).toFixed(2).replace(".", ",")} GB`;
}

function el(tag, props = {}, ...filhos) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (k === "class") n.className = v;
    else if (k === "text") n.textContent = v;
    else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
    else n.setAttribute(k, v);
  }
  for (const f of filhos) if (f != null) n.append(f);
  return n;
}

function aviso(texto) {
  const caixa = $("aviso");
  caixa.textContent = texto || "";
  caixa.hidden = !texto;
}

// --- Carregamento -----------------------------------------------------------

async function iniciarPagina() {
  try {
    estado = await api("/api/estado");
  } catch (e) {
    aviso(`Não foi possível conectar à ferramenta: ${e.message}`);
    return;
  }
  try {
    await api("/api/fuso", { method: "POST", body: JSON.stringify({ fuso: Intl.DateTimeFormat().resolvedOptions().timeZone }) });
  } catch (_) { /* sem fuso: as datas ficam em UTC, indicado no cabeçalho */ }
  $("versao").textContent = `versão ${estado.versao}`;
  $("pasta-audios").textContent = estado.pasta_audios;
  $("pasta-saida").textContent = estado.pasta_saida;

  const chip = $("chip-gpu");
  chip.textContent = estado.gpu ? `GPU: ${estado.gpu_nome || "NVIDIA"}` : "Sem GPU: usando CPU";
  chip.classList.toggle("ativo", estado.gpu);

  for (const m of estado.modelos) $("modelo").append(el("option", { value: m.id, text: m.id }));
  for (const i of estado.idiomas) $("idioma").append(el("option", { value: i.id, text: i.nome }));
  for (const d of estado.dispositivos) {
    const opcao = el("option", { value: d.id, text: d.nome });
    if (d.id === "cuda" && !estado.gpu) opcao.disabled = true;
    $("dispositivo").append(opcao);
  }
  $("modelo").value = estado.gpu ? "turbo" : "base";
  $("dispositivo").value = estado.dispositivo_padrao;
  $("dispositivo-info").textContent = estado.gpu
    ? "GPU NVIDIA detectada."
    : "Nenhuma GPU disponível: a transcrição usará o processador (mais lenta).";

  if (!estado.locutores_disponivel) {
    $("locutores").disabled = true;
    $("locutores-indisponivel").hidden = false;
  }

  atualizarDescricaoModelo();
  await Promise.all([carregarAudios(), carregarTranscricoes()]);

  const p = await api("/api/progresso");
  if (p.estado !== "ocioso") {
    mostrarAndamento(p);
    if (emAndamento(p)) acompanhar();
  }
}

async function carregarAudios() {
  const marcados = new Set(selecionados());
  const primeiraVez = audios.length === 0;
  const dados = await api("/api/audios");
  audios = dados.audios;
  if (!dados.pasta_existe) aviso("A pasta do caso não foi encontrada dentro da ferramenta. Verifique o config.txt e execute o lançador de novo.");

  const corpo = $("tabela-audios").querySelector("tbody");
  corpo.replaceChildren();
  for (const a of audios) {
    const caixa = el("input", { type: "checkbox", "data-arquivo": a.arquivo, onchange: atualizarResumo });
    // Na primeira carga, marca só o que ainda não foi transcrito.
    caixa.checked = primeiraVez ? a.transcricoes.length === 0 : marcados.has(a.arquivo);
    let transcricoes = el("span", { class: "pequeno", text: "—" });
    if (a.transcricoes.length) {
      transcricoes = el("span", {},
        ...a.transcricoes.map((t, i) => el("button", {
          class: "botao link", type: "button", text: i === 0 ? "ver" : `ver ${i + 1}`,
          title: t, onclick: () => abrirLeitor(t),
        })));
    }
    corpo.append(el("tr", {},
      el("td", {}, caixa),
      el("td", { class: "arquivo", text: a.arquivo }),
      el("td", { class: "num", text: duracao(a.duracao) }),
      el("td", { class: "num", text: tamanho(a.tamanho) }),
      el("td", {}, transcricoes)));
  }
  $("audios-vazio").hidden = audios.length > 0;
  $("tabela-audios").hidden = audios.length === 0;
  atualizarResumo();
}

async function carregarTranscricoes() {
  const dados = await api("/api/transcricoes");
  const corpo = $("tabela-transcricoes").querySelector("tbody");
  corpo.replaceChildren();
  for (const t of dados.arquivos) {
    const nome = t.tipo === "relatorio" ? `${t.arquivo} (relatório do lote)` : t.arquivo;
    corpo.append(el("tr", {},
      el("td", { class: "arquivo", text: nome }),
      el("td", { class: "pequeno", text: t.modelo || "" }),
      el("td", { class: "pequeno", text: t.gerado_em || t.modificado }),
      el("td", {}, el("button", { class: "botao link", type: "button", text: "ver", onclick: () => abrirLeitor(t.arquivo) }))));
  }
  $("transcricoes-vazio").hidden = dados.arquivos.length > 0;
  $("tabela-transcricoes").hidden = dados.arquivos.length === 0;
}

// --- Seleção e opções --------------------------------------------------------

function selecionados() {
  return [...document.querySelectorAll("#tabela-audios input[type=checkbox]:checked")].map((c) => c.dataset.arquivo);
}

function marcar(filtro) {
  for (const caixa of document.querySelectorAll("#tabela-audios input[type=checkbox]")) {
    const a = audios.find((x) => x.arquivo === caixa.dataset.arquivo);
    caixa.checked = filtro(a);
  }
  atualizarResumo();
}

function atualizarResumo() {
  const lista = selecionados();
  const total = lista.reduce((s, nome) => s + (audios.find((a) => a.arquivo === nome)?.duracao || 0), 0);
  $("resumo-selecao").textContent = audios.length
    ? `${lista.length} de ${audios.length} selecionado(s) · duração total ${duracao(total)}`
    : "";
  atualizarEstimativa(total, lista.length);
}

function atualizarDescricaoModelo() {
  const m = estado.modelos.find((x) => x.id === $("modelo").value);
  $("modelo-descricao").textContent = m ? m.descricao : "";
  atualizarResumo();
}

function atualizarEstimativa(totalSegundos, quantidade) {
  if (!estado) return;
  const botao = $("botao-iniciar");
  if (!quantidade) {
    $("estimativa").textContent = "Selecione ao menos um áudio.";
    botao.disabled = true;
    return;
  }
  botao.disabled = false;
  const disp = $("dispositivo").value === "cpu" || !estado.gpu ? "cpu" : "cuda";
  let fator = estado.velocidade[disp][$("modelo").value] || 1;
  if ($("locutores").checked) fator += estado.velocidade_locutores[disp];
  $("estimativa").textContent = `Tempo estimado: ${duracaoTexto(totalSegundos * fator)} (aproximado; o primeiro uso de cada modelo também faz o download).`;
}

// --- Transcrição -------------------------------------------------------------

async function iniciarTranscricao() {
  const arquivos = selecionados();
  if (!arquivos.length) return;
  const num = parseInt($("num-locutores").value, 10);
  const pedido = {
    arquivos,
    modelo: $("modelo").value,
    idioma: $("idioma").value,
    dispositivo: $("dispositivo").value,
    marcacao_tempo: $("marcacao-tempo").checked,
    locutores: $("locutores").checked,
    num_locutores: Number.isFinite(num) && num > 0 ? num : null,
  };
  aviso("");
  try {
    await api("/api/iniciar", { method: "POST", body: JSON.stringify(pedido) });
  } catch (e) {
    aviso(e.message);
    return;
  }
  $("tabela-resultados").querySelector("tbody").replaceChildren();
  acompanhar();
}

function emAndamento(p) {
  return p.estado === "carregando" || p.estado === "transcrevendo";
}

function acompanhar() {
  clearTimeout(consulta);
  bloquearOpcoes(true);
  const ciclo = async () => {
    let p;
    try {
      p = await api("/api/progresso");
    } catch (e) {
      aviso(`Conexão perdida com a ferramenta: ${e.message}`);
      consulta = setTimeout(ciclo, 3000);
      return;
    }
    mostrarAndamento(p);
    if (emAndamento(p)) {
      consulta = setTimeout(ciclo, 1000);
    } else {
      bloquearOpcoes(false);
      await Promise.all([carregarAudios(), carregarTranscricoes()]);
    }
  };
  ciclo();
}

function bloquearOpcoes(bloquear) {
  for (const id of ["botao-iniciar", "modelo", "idioma", "dispositivo", "marcacao-tempo", "num-locutores"]) $(id).disabled = bloquear;
  $("locutores").disabled = bloquear || !estado.locutores_disponivel;
  for (const c of document.querySelectorAll("#tabela-audios input[type=checkbox]")) c.disabled = bloquear;
  if (!bloquear) atualizarResumo();
}

function mostrarAndamento(p) {
  $("secao-andamento").hidden = false;
  const rodando = emAndamento(p);
  $("botao-cancelar").hidden = !rodando;
  const textos = {
    carregando: "Carregando o modelo… (no primeiro uso, ele é baixado da internet)",
    transcrevendo: `Transcrevendo ${p.indice + 1} de ${p.total}: ${p.arquivo_atual || ""}`,
    concluido: `Concluído: ${p.resultados.filter((r) => r.sucesso).length} de ${p.total} arquivo(s) transcrito(s).`,
    cancelado: `Cancelado. ${p.resultados.length} arquivo(s) processado(s) antes do cancelamento.`,
    erro: p.mensagem || "Erro.",
  };
  $("andamento-estado").textContent = textos[p.estado] || "";
  $("andamento-estado").className = `andamento-estado ${p.estado === "erro" ? "situacao-erro" : ""}`;

  const pa = rodando ? p.progresso_arquivo : (p.estado === "concluido" ? 1 : p.progresso_arquivo);
  const pt = p.estado === "concluido" ? 1 : p.progresso_geral;
  $("barra-arquivo").style.width = `${(pa * 100).toFixed(1)}%`;
  $("barra-total").style.width = `${(pt * 100).toFixed(1)}%`;
  $("pct-arquivo").textContent = `${Math.round(pa * 100)}%`;
  $("pct-total").textContent = `${Math.round(pt * 100)}%`;

  let tempos = `Decorrido: ${duracao(p.decorrido)}`;
  if (rodando && p.restante != null) tempos += ` · Restante: ${duracaoTexto(p.restante)}`;
  if (p.opcoes && p.opcoes.dispositivo_usado) tempos += ` · ${p.opcoes.modelo} em ${p.opcoes.dispositivo_usado}`;
  $("tempos").textContent = tempos;

  const corpo = $("tabela-resultados").querySelector("tbody");
  corpo.replaceChildren();
  for (const r of p.resultados) {
    corpo.append(el("tr", {},
      el("td", { class: "arquivo", text: r.arquivo }),
      el("td", { class: r.sucesso ? "situacao-ok" : "situacao-erro", text: r.sucesso ? "ok" : `erro: ${r.erro || ""}` }),
      el("td", { class: "num", text: r.tempo != null ? duracao(r.tempo) : "—" }),
      el("td", { class: "num", text: r.sucesso ? `${r.baixa_confianca} de ${r.trechos}` : "—" }),
      el("td", { class: "num", text: p.opcoes && p.opcoes.locutores && r.sucesso ? String(r.locutores) : "—" }),
      el("td", {}, r.transcricao ? el("button", { class: "botao link", type: "button", text: "ver", onclick: () => abrirLeitor(r.transcricao) }) : null)));
  }
  $("tabela-resultados").hidden = p.resultados.length === 0;
  $("relatorio-info").textContent = p.relatorio
    ? `Relatório do lote (com os hashes SHA-256) gravado em: ${p.relatorio}`
    : "";
}

// --- Leitor ------------------------------------------------------------------

const RE_TEMPO = /^\[(\d\d:\d\d:\d\d) - (\d\d:\d\d:\d\d)\]\s*/;
const RE_LOCUTOR = /^(LOCUTOR (\d+|\?)):\s*/;
const RE_DUVIDA = /\[\?\? ([\s\S]*?) \?\?\]/g;

function renderizarTranscricao(texto) {
  const caixa = document.createDocumentFragment();
  for (let linha of texto.replace(/\r/g, "").split("\n")) {
    if (linha.startsWith("#")) {
      caixa.append(el("p", { class: "linha cabecalho", text: linha }));
      continue;
    }
    if (!linha.trim()) continue;
    const p = el("p", { class: "linha" });
    const t = linha.match(RE_TEMPO);
    if (t) {
      p.append(el("span", { class: "tempo", text: `${t[1]}–${t[2]}` }));
      linha = linha.slice(t[0].length);
    }
    const l = linha.match(RE_LOCUTOR);
    if (l) {
      const classe = l[2] === "?" ? "loc-desconhecido" : `loc-${(parseInt(l[2], 10) - 1) % 6}`;
      p.append(el("span", { class: `locutor ${classe}`, text: `${l[1]}:` }));
      linha = linha.slice(l[0].length);
    }
    let ultimo = 0;
    for (const m of linha.matchAll(RE_DUVIDA)) {
      p.append(linha.slice(ultimo, m.index));
      p.append(el("mark", { class: "duvida", title: "Baixa confiança: confira no áudio", text: m[1] }));
      ultimo = m.index + m[0].length;
    }
    p.append(linha.slice(ultimo));
    caixa.append(p);
  }
  return caixa;
}

function renderizarRelatorio(texto) {
  const linhas = texto.replace(/\r/g, "").split("\n").filter((l) => l.trim());
  const tabela = el("table", { class: "tabela" });
  linhas.forEach((linha, i) => {
    const celulas = linha.split(";").map((c) => el(i === 0 ? "th" : "td", { text: c.replace(/^"|"$/g, "") }));
    tabela.append(el("tr", {}, ...celulas));
  });
  return el("div", { class: "tabela-rolagem" }, tabela);
}

async function abrirLeitor(caminho) {
  $("leitor-titulo").textContent = caminho;
  const conteudo = $("leitor-conteudo");
  conteudo.replaceChildren(el("p", { class: "pequeno", text: "Carregando…" }));
  $("leitor").hidden = false;
  try {
    const texto = await api(`/api/arquivo?caminho=${encodeURIComponent(caminho)}`);
    conteudo.replaceChildren(caminho.toLowerCase().endsWith(".csv") ? renderizarRelatorio(texto) : renderizarTranscricao(texto));
  } catch (e) {
    conteudo.replaceChildren(el("p", { class: "situacao-erro", text: e.message }));
  }
  $("leitor-fechar").focus();
}

function fecharLeitor() { $("leitor").hidden = true; }

// --- Encerrar ----------------------------------------------------------------

async function encerrar() {
  let p = null;
  try { p = await api("/api/progresso"); } catch (_) { /* segue */ }
  const rodando = p && emAndamento(p);
  const pergunta = rodando
    ? "Há uma transcrição em andamento. Encerrar mesmo assim? O arquivo atual será perdido (os já concluídos ficam gravados)."
    : "Encerrar o audio2text?";
  if (!confirm(pergunta)) return;
  try {
    await api(`/api/encerrar${rodando ? "?forcar=true" : ""}`, { method: "POST" });
  } catch (e) {
    aviso(e.message);
    return;
  }
  clearTimeout(consulta);
  $("encerrado").hidden = false;
}

// --- Eventos -----------------------------------------------------------------

$("marcar-todos").addEventListener("click", () => marcar(() => true));
$("marcar-nenhum").addEventListener("click", () => marcar(() => false));
$("marcar-pendentes").addEventListener("click", () => marcar((a) => a.transcricoes.length === 0));
$("modelo").addEventListener("change", atualizarDescricaoModelo);
$("dispositivo").addEventListener("change", atualizarResumo);
$("locutores").addEventListener("change", () => {
  $("campo-num-locutores").hidden = !$("locutores").checked;
  atualizarResumo();
});
$("botao-iniciar").addEventListener("click", iniciarTranscricao);
$("botao-cancelar").addEventListener("click", async () => {
  if (confirm("Cancelar a transcrição? Os arquivos já concluídos ficam gravados.")) await api("/api/cancelar", { method: "POST" });
});
$("botao-encerrar").addEventListener("click", encerrar);
$("leitor-fechar").addEventListener("click", fecharLeitor);
$("leitor").addEventListener("click", (e) => { if (e.target === $("leitor")) fecharLeitor(); });
document.addEventListener("keydown", (e) => { if (e.key === "Escape") fecharLeitor(); });
$("copiar-saida").addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText(estado.pasta_saida);
    $("copiar-saida").textContent = "Caminho copiado";
    setTimeout(() => { $("copiar-saida").textContent = "Copiar caminho da pasta"; }, 2000);
  } catch (_) {
    prompt("Copie o caminho:", estado.pasta_saida);
  }
});

iniciarPagina();
