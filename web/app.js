const $ = s => document.querySelector(s);
const $$ = s => [...document.querySelectorAll(s)];

const esc = x =>
  String(x ?? '').replace(
    /[&<>"']/g,
    c => ({
      '&': '&amp;',
      '<': '&lt;',
      '>': '&gt;',
      '"': '&quot;',
      "'": '&#039;'
    }[c])
  );


let currentStatus = 'ACTIVE';
let allMemories = [];


// ------------------------------------------------------------
// NAVIGATION
// ------------------------------------------------------------

function show(view) {

  $$('.view').forEach(x =>
    x.classList.toggle('active', x.id === view)
  );

  $$('.nav').forEach(x =>
    x.classList.toggle(
      'active',
      x.dataset.view === view
    )
  );

  if (view === 'memory') {
    loadMem();
  }
}


$$('.nav').forEach(x =>
  x.onclick = () => show(x.dataset.view)
);


// ------------------------------------------------------------
// HEY KIVI
// ------------------------------------------------------------

$$('.chips button').forEach(x => {

  x.onclick = () => {

    $('#q').value = x.textContent;

    ask();
  };

});


$('#askbtn').onclick = ask;


$('#q').addEventListener('keydown', e => {

  if (
    (e.ctrlKey || e.metaKey) &&
    e.key === 'Enter'
  ) {
    ask();
  }

});


async function ask() {

  const q = $('#q').value.trim();

  if (!q) return;

  const box = $('#answer');

  box.classList.remove('hidden');

  box.innerHTML =
    '<div class="muted">Checking your memory…</div>';


  try {

    const r = await fetch(
      '/api/hey-kivi',
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          question: q
        })
      }
    );


    const d = await r.json();

    if (!r.ok) {
      throw Error(
        d.detail || 'Request failed'
      );
    }


    renderAnswer(d);

  } catch (e) {

    box.innerHTML =
      `<div class="reason">${esc(e.message)}</div>`;

  }

}


function renderAnswer(d) {

  const verdict =
    d.evidence_verdict || 'UNSUPPORTED';

  const cls =
    verdict.toLowerCase();

  const prov =
    d.provenance || [];


  const evidence =
    prov
      .slice(0, 8)
      .map(p => {

        const text =
          p.evidence ||
          p.formatted_text ||
          '';

        return `
          <div class="evidence-item">

            <small>
              Transcript ${esc(p.transcript_id)}
              ${p.timestamp
                ? ' · ' + esc(p.timestamp)
                : ''}
            </small>

            “${esc(text)}”

          </div>
        `;

      })
      .join('');


  const showEvidence =
    evidence &&
    verdict !== 'UNSUPPORTED';


  $('#answer').innerHTML = `

    <div class="answer-top">

      <span class="verdict ${cls}">
        ${esc(verdict)}
      </span>

      <span class="latency">
        ${esc(d.latency_ms)} ms
      </span>

    </div>


    <div class="answer-text">
      ${esc(d.answer)}
    </div>


    <div class="reason">
      ${esc(d.evidence_reason)}
    </div>


    ${
      showEvidence
        ? `
          <div class="why">

            <button
              onclick="
                this
                  .nextElementSibling
                  .classList
                  .toggle('hidden')
              "
            >
              Why does Kivi know this? ↗
            </button>


            <div class="evidence-list hidden">
              ${evidence}
            </div>

          </div>
        `
        : ''
    }

  `;
}


// ------------------------------------------------------------
// MEMORY LIST
// ------------------------------------------------------------

$('#refresh').onclick = loadMem;


$$('.tab').forEach(t => {

  t.onclick = () => {

    $$('.tab').forEach(
      x => x.classList.remove('active')
    );

    t.classList.add('active');

    currentStatus =
      t.dataset.status;

    loadMem();

  };

});


$('#memory-search')
  .addEventListener(
    'input',
    filterMemories
  );


async function loadMem() {

  const b = $('#memories');

  b.innerHTML =
    '<p class="muted">Loading…</p>';


  try {

    const r = await fetch(
      `/api/memories?status=${currentStatus}&limit=500`
    );

    allMemories = await r.json();

    renderStats();

    filterMemories();

  } catch (e) {

    b.innerHTML =
      `<p class="muted">${esc(e.message)}</p>`;

  }

}


function renderStats() {

  $('#memory-stats').innerHTML = `

    <div class="stat">

      <b>${allMemories.length}</b>

      ${currentStatus.toLowerCase()}

    </div>


    <div class="stat">

      <b>
        ${
          allMemories.filter(
            m => m.type === 'FACT'
          ).length
        }
      </b>

      facts

    </div>


    <div class="stat">

      <b>
        ${
          allMemories.filter(
            m => m.type === 'PREFERENCE'
          ).length
        }
      </b>

      preferences

    </div>


    <div class="stat">

      <b>
        ${
          allMemories.filter(
            m => m.type === 'EPISODE'
          ).length
        }
      </b>

      episodes

    </div>

  `;
}


function filterMemories() {

  const q =
    $('#memory-search')
      .value
      .trim()
      .toLowerCase();


  const ms =
    allMemories.filter(
      m =>
        !q ||
        JSON.stringify(m)
          .toLowerCase()
          .includes(q)
    );


  $('#memories').innerHTML =
    ms.length
      ? ms.map(memoryCard).join('')
      : '<p class="muted">No memories match.</p>';

}


function memoryCard(m) {

  const c =
    m.content || {};


  const val =
    c.value ??
    c.summary ??
    (
      c.attribute
        ? `${c.attribute}: ${JSON.stringify(c)}`
        : JSON.stringify(c)
    );


  const conf =
    Math.round(
      (m.confidence || 0) * 100
    );


  const statusClass =
    m.status === 'ACTIVE'
      ? 'supported'
      : m.status === 'UNCERTAIN'
        ? 'uncertain'
        : 'contradicted';


  return `

    <article
      class="mem-card"
      onclick="openMemory(${m.id})"
    >

      <div class="mem-head">

        <span class="type">
          ${esc(m.type)}
        </span>

        <span
          class="status ${statusClass}"
        >
          ${esc(m.status)}
        </span>

      </div>


      <h3>
        ${esc(m.title)}
      </h3>


      <div class="mem-value">
        ${esc(val)}
      </div>


      <div class="mem-subject">
        ${esc(m.subject)}
      </div>


      <div class="confidence">

        Confidence ${conf}%

        <div class="bar">
          <i style="width:${conf}%"></i>
        </div>

      </div>

    </article>

  `;

}


// ------------------------------------------------------------
// MEMORY DETAIL
// ------------------------------------------------------------

window.openMemory = async id => {

  const modal = $('#modal');

  $('#modal-content').innerHTML =
    '<p>Loading…</p>';

  modal.classList.remove('hidden');


  try {

    const r =
      await fetch(
        `/api/memories/${id}`
      );


    const m =
      await r.json();


    if (!r.ok) {

      throw Error(
        m.detail || 'Not found'
      );

    }


    renderMemoryDetail(m);

  } catch (e) {

    $('#modal-content').innerHTML =
      `<p>${esc(e.message)}</p>`;

  }

};


function renderMemoryDetail(m) {

  const c =
    m.content || {};


  const val =
    c.value ??
    c.summary ??
    JSON.stringify(c);


  const sources =
    m.sources || [];


  const history =
    m.history || [];


  const sourceHtml =
    sources.length

      ? sources
          .map(s => `

            <div class="timeline-item">

              <b>
                Transcript ${esc(s.transcript_id)}
              </b>

              ${esc(
                s.evidence ||
                s.formatted_text ||
                ''
              )}

            </div>

          `)
          .join('')

      : '<span class="muted">No source transcript.</span>';


  const historyHtml =
    history
      .map(h => `

        <div class="timeline-item">

          <b>
            ${esc(h.event_type)}
          </b>

          ${esc(h.reason)}

        </div>

      `)
      .join('');


  $('#modal-content').innerHTML = `

    <div class="eyebrow">
      ${esc(m.type)} · ${esc(m.status)}
    </div>


    <div class="detail-title">
      ${esc(m.title)}
    </div>


    <div class="detail-value">

      <b>${esc(m.subject)}</b>

      ${
        c.attribute
          ? ` · ${esc(c.attribute)}`
          : ''
      }

      <br>

      ${esc(val)}

    </div>


    <div class="detail-section">

      <h4>WHY KIVI KNOWS</h4>

      <div class="timeline">
        ${sourceHtml}
      </div>

    </div>


    ${
      history.length
        ? `

          <div class="detail-section">

            <h4>MEMORY HISTORY</h4>

            <div class="timeline">
              ${historyHtml}
            </div>

          </div>

        `
        : ''
    }


    <div class="action-row">

      ${
        m.status !== 'DELETED'
          ? `
            <button
              class="secondary"
              onclick="deleteMemory(${m.id})"
            >
              Delete memory
            </button>
          `
          : ''
      }

    </div>

  `;

}


window.deleteMemory = async id => {

  if (
    !confirm(
      'Remove this memory from your active memory?'
    )
  ) {
    return;
  }


  const r =
    await fetch(
      `/api/memories/${id}`,
      {
        method: 'DELETE'
      }
    );


  if (!r.ok) {

    alert(
      'Could not delete memory'
    );

    return;

  }


  $('#modal')
    .classList
    .add('hidden');


  loadMem();

};


// ------------------------------------------------------------
// MODAL
// ------------------------------------------------------------

$('#modal-close').onclick = () =>
  $('#modal')
    .classList
    .add('hidden');


$('.modal-backdrop').onclick = () =>
  $('#modal')
    .classList
    .add('hidden');


// ------------------------------------------------------------
// ADD CONTEXT
// ------------------------------------------------------------

$('#process').onclick =
  processTranscript;


async function processTranscript() {

  const text =
    $('#t').value.trim();


  if (!text) return;


  $('#result').innerHTML =
    '<p>Processing transcript…</p>';


  try {

    const r =
      await fetch(
        '/api/transcripts',
        {
          method: 'POST',

          headers: {
            'Content-Type':
              'application/json'
          },

          body: JSON.stringify({

            timestamp:
              new Date().toISOString(),

            raw_asr:
              text,

            formatted_text:
              text,

            metadata: {
              source: 'kivi-ui'
            }

          })

        }
      );


    const t =
      await r.json();


    if (!r.ok) {

      throw Error(
        t.detail ||
        'Could not save transcript'
      );

    }


    const p =
      await fetch(
        `/api/transcripts/${t.id}/process-memory`,
        {
          method: 'POST'
        }
      );


    const d =
      await p.json();


    if (!p.ok) {

      throw Error(
        d.detail ||
        'Could not process transcript'
      );

    }


    const dec =
      d.decision || {};


    const m =
      d.memory;


    $('#result').innerHTML = `

      <span class="decision-pill">
        ${esc(dec.decision)}
      </span>


      <div class="result-value">
        ${esc(dec.reason || '')}
      </div>


      ${
        m
          ? `

            <div class="result-reason">

              <b>${esc(m.title)}</b>

              <br>

              ${esc(
                (m.content || {}).value ??
                (m.content || {}).summary ??
                ''
              )}

            </div>

          `
          : ''
      }

    `;


    $('#t').value = '';


  } catch (e) {

    $('#result').innerHTML =
      `<p class="danger">${esc(e.message)}</p>`;

  }

}