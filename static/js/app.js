const API_URL = "/api/ask";
const micBtn = document.getElementById("micBtn");
const askBtn = document.getElementById("askBtn");
const questionInput = document.getElementById("questionInput");
const questionText = document.getElementById("questionText");
const answerText = document.getElementById("answerText");
const winesGrid = document.getElementById("winesGrid");
const statusEl = document.getElementById("status");
const loadingEl = document.getElementById("loading");

const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
const hasSpeechRecognition = Boolean(SpeechRecognition);
let recognition = null;
let isListening = false;

if (hasSpeechRecognition) {
  recognition = new SpeechRecognition();
  recognition.lang = "en-US";
  recognition.continuous = false;
  recognition.interimResults = false;

  recognition.onresult = (event) => {
    const transcript = event.results[0][0].transcript;
    questionInput.value = transcript;
    submitQuestion(transcript);
  };

  recognition.onstart = () => {
    isListening = true;
    micBtn.classList.add("listening");
    statusEl.textContent = "Listening...";
  };

  recognition.onend = () => {
    isListening = false;
    micBtn.classList.remove("listening");
    if (!loadingEl.classList.contains("show")) {
      statusEl.textContent = "Ready to listen or type.";
    }
  };

  recognition.onerror = () => {
    statusEl.textContent = "Voice recognition failed. You can still type your question.";
  };
} else {
  statusEl.textContent = "SpeechRecognition not supported in this browser. Use text input.";
  micBtn.disabled = true;
  micBtn.style.opacity = "0.6";
  micBtn.style.cursor = "not-allowed";
}

micBtn.addEventListener("click", () => {
  if (!recognition) return;
  if (isListening) {
    recognition.stop();
  } else {
    recognition.start();
  }
});

askBtn.addEventListener("click", () => submitQuestion(questionInput.value));
questionInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    submitQuestion(questionInput.value);
  }
});

function formatPrice(price) {
  const parsed = Number(price);
  return Number.isFinite(parsed) ? `$${parsed.toFixed(2)}` : "N/A";
}

function bestRatingText(wine) {
  const rating = wine.best_rating || {};
  if (rating.score == null || rating.max_score == null) return "No professional rating";
  const source = rating.source ? ` (${rating.source})` : "";
  return `${rating.score}/${rating.max_score}${source}`;
}

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text ?? "";
  return div.innerHTML;
}

function renderWines(wines) {
  if (!Array.isArray(wines) || wines.length === 0) {
    winesGrid.innerHTML = "";
    return;
  }

  winesGrid.innerHTML = wines.map((wine) => {
    const color = (wine.color || "red").toLowerCase();
    const colorClass = ["red", "white", "rose", "sparkling"].includes(color) ? color : "red";
    const safeImage = wine.image_url || "https://placehold.co/600x400/201920/F4EDE1?text=Wine";
    const name = escapeHtml(wine.name || "Unknown Wine");
    const producer = escapeHtml(wine.producer || "Unknown Producer");
    const region = escapeHtml([wine.region, wine.country].filter(Boolean).join(", "));
    const varietal = escapeHtml(wine.varietal || "Varietal N/A");
    const rating = escapeHtml(bestRatingText(wine));
    const link = wine.reference_url ? `<a class="link" href="${wine.reference_url}" target="_blank" rel="noopener noreferrer">View bottle</a>` : "";

    return `
      <article class="wine-card">
        <img src="${safeImage}" alt="${name}" onerror="this.src='https://placehold.co/600x400/201920/F4EDE1?text=Wine'" />
        <div class="wine-content">
          <h4 class="wine-title">${name}</h4>
          <div class="meta">${producer}</div>
          <div class="meta">${region}</div>
          <div class="meta">${varietal}</div>
          <span class="badge ${colorClass}">${escapeHtml(color)}</span>
          <div class="price">${formatPrice(wine.price)}</div>
          <div class="rating">Top rating: ${rating}</div>
          ${link}
        </div>
      </article>
    `;
  }).join("");
}

function speak(text) {
  if (!("speechSynthesis" in window) || !text) return;
  window.speechSynthesis.cancel();
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.rate = 1;
  utterance.pitch = 1;
  utterance.lang = "en-US";
  window.speechSynthesis.speak(utterance);
}

async function submitQuestion(question) {
  const cleaned = (question || "").trim();
  if (!cleaned) {
    statusEl.textContent = "Ask a wine-related question to get started.";
    return;
  }

  questionText.textContent = cleaned;
  answerText.textContent = "Thinking...";
  loadingEl.classList.add("show");
  askBtn.disabled = true;
  statusEl.textContent = "Finding the best matches...";

  try {
    const response = await fetch(API_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question: cleaned })
    });

    if (!response.ok) {
      throw new Error(`Request failed with status ${response.status}`);
    }

    const data = await response.json();
    answerText.textContent = data.answer || "No answer returned.";
    renderWines(data.wines || []);
    speak(data.answer || "");
    statusEl.textContent = "Ready for your next question.";
  } catch (error) {
    answerText.textContent = "I could not reach the wine assistant API. Make sure the FastAPI server is running.";
    winesGrid.innerHTML = "";
    statusEl.textContent = "API unavailable. Start backend and try again.";
  } finally {
    loadingEl.classList.remove("show");
    askBtn.disabled = false;
  }
}
