# Release day: switch lurisapp.com from "Coming soon" to the App Store

Until Apple publishes the product page, `https://apps.apple.com/app/id6813596103`
returns 404, so the site links to nothing on the App Store and shows
"Coming soon to the App Store" instead. Do this only once the product page opens in a
browser.

## The one step

```bash
cd ~/Developer/Luris-Website
python3 _tools/build_pages.py release --pt PROVIDER_TOKEN && python3 _tools/validate.py
git add -A && git commit -m "switch the site to the live App Store listing - Luris is released" && git push origin main
```

`PROVIDER_TOKEN` is the number after `pt=` in any campaign link from App Store Connect
(App Analytics, Acquisition, Campaigns, Generate a campaign link). It is the same for
every app on the account. If you do not have it to hand, leave `--pt PROVIDER_TOKEN` out:
the links still work, they just are not attributed to a campaign. You can run the
command again later with the token.

That command:

1. Replaces "Coming soon" with Apple's official black "Download on the App Store" badge
   in the hero (`img/badges/app-store-black-en-us.svg`, downloaded from Apple's marketing
   toolbox; one badge per page, 50 px tall, never altered), and with a "Get Luris on the
   App Store" button in the closing panel.
2. Turns the header's "Coming soon" chip into a "Get Luris" button on every page, and
   adds an "App Store" link to every footer.
3. Gives every link its own campaign code so App Analytics shows which placement brings
   downloads, with no analytics on the site: `web-header`, `web-hero`, `web-final`,
   `web-footer`, `web-qr`, `web-support`.
4. Adds the Smart App Banner (`<meta name="apple-itunes-app" content="app-id=6813596103">`)
   to every page.
5. Adds a QR code (dark on white, encoded with the `web-qr` link) next to the badge and
   in the closing panel, shown only to desktop visitors with a mouse.
6. Adds `downloadUrl` and `sameAs` to the JSON-LD and refreshes `sitemap.xml`.

The state is kept in `_tools/release.json`. The validator fails if any page disagrees
with it (an App Store link before release, a link without its campaign code after).

## Then check, on real devices

- iPhone, Safari, `https://lurisapp.com`: the Smart App Banner shows (it never shows in
  the simulator or before the app is live in your country), tapping it opens the
  product page, and the badge opens the App Store app.
- Mac: scan the QR code with an iPhone camera; it opens the product page.
- Search Console: request indexing of `https://lurisapp.com/`.
- Lighthouse on `/` (mobile and desktop) should still be 100 in all four categories.

## If Apple's badge rules change

Official badge artwork only, from https://toolbox.marketingtools.apple.com (the SVG is
self-hosted because the site loads nothing from other origins). No Apple logo anywhere
else on the site, and never a home-made badge.
