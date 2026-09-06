/* Reusable quiz widget: immediate feedback, running score, no formatting leaks.
   Usage: initQuiz("quiz-mount", [...questions]) — see lessons for the JSON shape. */
function initQuiz(mountId, questions) {
  const mount = document.getElementById(mountId);
  const wrapper = document.createElement("div");
  wrapper.className = "quiz";
  let score = 0;
  let answered = 0;

  questions.forEach((q, qIndex) => {
    const box = document.createElement("div");
    box.className = "question";
    const text = document.createElement("p");
    text.className = "qtext";
    text.textContent = `${qIndex + 1}. ${q.q}`;
    box.appendChild(text);

    const feedback = document.createElement("p");
    feedback.className = "feedback";

    q.options.forEach((option, oIndex) => {
      const button = document.createElement("button");
      button.className = "option";
      button.textContent = option;
      button.onclick = () => {
        const isCorrect = oIndex === q.answer;
        if (isCorrect) score += 1;
        answered += 1;
        box.querySelectorAll("button").forEach((b, i) => {
          b.disabled = true;
          if (i === q.answer) b.classList.add("correct");
        });
        if (!isCorrect) button.classList.add("incorrect");
        feedback.textContent = isCorrect ? "Correct." : q.why;
        if (answered === questions.length) showScore();
      };
      box.appendChild(button);
    });
    box.appendChild(feedback);
    wrapper.appendChild(box);
  });

  const scoreLine = document.createElement("p");
  scoreLine.className = "score";
  wrapper.appendChild(scoreLine);

  function showScore() {
    scoreLine.textContent = `Score: ${score}/${questions.length} — recall this tomorrow without looking; that is the real test.`;
  }

  mount.appendChild(wrapper);
}
