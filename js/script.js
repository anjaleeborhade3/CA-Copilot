// Get Started buttons
const getStartedButtons = document.querySelectorAll(
    ".login-btn, .primary-btn"
);

getStartedButtons.forEach(button => {
    button.addEventListener("click", () => {
        document.querySelector("#workflow").scrollIntoView({
            behavior: "smooth"
        });
    });
});


// Explore Features button
const exploreButton = document.querySelector(".secondary-btn");

exploreButton.addEventListener("click", () => {
    document.querySelector("#features").scrollIntoView({
        behavior: "smooth"
    });
});


// Feature cards interaction
const featureCards = document.querySelectorAll(".feature-card");

featureCards.forEach(card => {
    const toggleCard = () => {
        const isSelected = card.classList.toggle("selected");
        card.setAttribute("aria-pressed", String(isSelected));
    };

    card.addEventListener("click", () => {
        toggleCard();
    });

    card.addEventListener("keydown", event => {
        if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            toggleCard();
        }
    });
});


// Console confirmation
console.log("FinPilot loaded successfully!");