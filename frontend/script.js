const form = document.getElementById('analyzeForm');
const submitBtn = document.getElementById('submitBtn');
const resultDiv = document.getElementById('result');
const atsScoreEl = document.getElementById('atsScore');
const sectionScoresEl = document.getElementById('sectionScores');
const missingKeywordsEl = document.getElementById('missingKeywords');
const suggestionsEl = document.getElementById('suggestions');
const debugTextsEl = document.getElementById('debugTexts');

form.addEventListener('submit', async (e) => {
  e.preventDefault();
  submitBtn.disabled = true;
  submitBtn.textContent = 'Analyzing...';

  const formData = new FormData();
  const fileInput = document.getElementById('resume');
  const file = fileInput && fileInput.files && fileInput.files[0];
  if (!file) {
    alert('Please select a resume file before submitting.');
    submitBtn.disabled = false;
    submitBtn.textContent = 'Analyze';
    return;
  }
  const jd = document.getElementById('jd').value || '';

  formData.append('resume', file);
  formData.append('jd', jd);

  try {
    const res = await fetch('https://resume-analyzer-2-wa95.onrender.com/api/analyze', {
      method: 'POST',
      body: formData
    });

    // If server returned non-2xx, attempt to read JSON or plain text and show to user
    if (!res.ok) {
      const contentType = res.headers.get('content-type') || '';
      let errText = res.status + ' ' + res.statusText;
      if (contentType.includes('application/json')) {
        const errJson = await res.json();
        errText = JSON.stringify(errJson, null, 2);
      } else {
        const txt = await res.text();
        if (txt) errText = txt;
      }
      throw new Error(errText);
    }

    const data = await res.json();

    if (data.error) {
      throw new Error(data.error || 'Server returned an error');
    }

    // show results
    resultDiv.classList.remove('hidden');

    // ats score
    const ats = Number(data.ats_score) || 0;
    atsScoreEl.textContent = ats.toFixed(1) + '%';

    // section scores
    sectionScoresEl.innerHTML = '';
    if (data.section_scores && typeof data.section_scores === 'object') {
      Object.entries(data.section_scores).forEach(([k, v]) => {
        const li = document.createElement('li');
        const val = Number(v) || 0;
        li.textContent = `${k}: ${val.toFixed(1)}%`;
        sectionScoresEl.appendChild(li);
      });
    }

    // missing keywords
    missingKeywordsEl.innerHTML = '';
    (data.missing_keywords || []).slice(0, 50).forEach(k => {
      const li = document.createElement('li');
      li.textContent = k;
      missingKeywordsEl.appendChild(li);
    });

    // suggestions
    suggestionsEl.innerHTML = '';
    (data.suggestions || []).forEach(s => {
      const li = document.createElement('li');
      li.textContent = s;
      suggestionsEl.appendChild(li);
    });

    // debug text
    debugTextsEl.textContent =
      '--- RESUME ---\n' + (data.debug && data.debug.resume_text ? data.debug.resume_text : '') +
      '\n\n--- JOB DESCRIPTION ---\n' + (data.debug && data.debug.jd_text ? data.debug.jd_text : '');

  } catch (err) {
    console.error('Analyze error:', err);
    alert('Error: ' + (err.message || err));
  } finally {
    submitBtn.disabled = false;
    submitBtn.textContent = 'Analyze';
  }
});
