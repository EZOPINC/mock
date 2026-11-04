// Navigation stays visible when JavaScript is unavailable.
const menuButton = document.querySelector('.menu-toggle');
const navigation = document.querySelector('#primary-navigation');
if (menuButton && navigation) {
  const mobile = window.matchMedia('(max-width: 70rem)');
  const setExpanded = (expanded) => {
    menuButton.setAttribute('aria-expanded', String(expanded));
    navigation.hidden = !expanded;
  };
  const synchronize = () => {
    const focusInside = navigation.contains(document.activeElement);
    menuButton.hidden = !mobile.matches;
    setExpanded(!mobile.matches);
    if (mobile.matches && focusInside) menuButton.focus();
    if (!mobile.matches && document.activeElement === menuButton) {
      navigation.querySelector('a').focus();
    }
  };
  menuButton.addEventListener('click', () => {
    setExpanded(menuButton.getAttribute('aria-expanded') !== 'true');
  });
  navigation.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && mobile.matches) {
      setExpanded(false);
      menuButton.focus();
    }
  });
  menuButton.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && mobile.matches) setExpanded(false);
  });
  document.addEventListener('click', (event) => {
    if (mobile.matches && !navigation.contains(event.target) && !menuButton.contains(event.target)) {
      const restoreFocus = navigation.contains(document.activeElement);
      setExpanded(false);
      if (restoreFocus) menuButton.focus();
    }
  });
  mobile.addEventListener('change', synchronize);
  synchronize();
}
