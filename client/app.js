const output = document.getElementById("output");
const button = document.getElementById("load");
const userInput = document.getElementById("user");

button.addEventListener("click", async () => {
  output.textContent = "Loading...";
  try {
    const res = await fetch("http://127.0.0.1:8000/api/v1/projects", {
      headers: { "x-user-id": userInput.value.trim() },
    });
    const data = await res.json();
    output.textContent = JSON.stringify(data, null, 2);
  } catch (err) {
    output.textContent = String(err);
  }
});
