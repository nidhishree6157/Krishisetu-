function setLogo(selector, theme) {
  const logo = document.querySelector(selector);
  if (!logo) return;

  if (theme === "dark") {
    logo.src = "/frontend/assets/logo/logo-circle-white.png";
  } else {
    logo.src = "/frontend/assets/logo/logo-circle-green.png";
  }
}

window.initializeLogos = function () {
  setLogo("#sidebarLogo", "dark");
  setLogo("#navbarLogo", "light");
};
