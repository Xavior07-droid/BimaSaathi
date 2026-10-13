/* BimaSaathi push service worker (F22). Handles notifications while the app is closed.
 * The Firebase web config is passed in the registration URL (?apiKey=...) because a service worker
 * cannot read NEXT_PUBLIC_* env vars. These values are public by design (no secrets here). */
/* eslint-disable no-undef */
importScripts('https://www.gstatic.com/firebasejs/10.14.1/firebase-app-compat.js');
importScripts('https://www.gstatic.com/firebasejs/10.14.1/firebase-messaging-compat.js');

const q = new URL(self.location.href).searchParams;
const config = {
  apiKey: q.get('apiKey'),
  authDomain: q.get('authDomain'),
  projectId: q.get('projectId'),
  appId: q.get('appId'),
  messagingSenderId: q.get('messagingSenderId'),
};

if (config.apiKey && config.messagingSenderId && config.projectId && config.appId) {
  firebase.initializeApp(config);
  const messaging = firebase.messaging();
  messaging.onBackgroundMessage((payload) => {
    // If the message has a "notification" part the browser already shows it: do not show a second one.
    if (payload.notification) return;
    const d = payload.data || {};
    self.registration.showNotification(d.title || 'BimaSaathi', {
      body: d.body || '',
      icon: '/icons/icon-192.png',
      data: { link: d.link || '/renewals' },
    });
  });
}

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const d = event.notification.data || {};
  const link = (d.FCM_MSG && d.FCM_MSG.data && d.FCM_MSG.data.link) || d.link || '/renewals';
  const target = new URL(link, self.location.origin).href;
  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((list) => {
      for (const c of list) {
        if (c.url.startsWith(self.location.origin) && 'focus' in c) {
          c.navigate(target);
          return c.focus();
        }
      }
      return self.clients.openWindow(target);
    }),
  );
});
