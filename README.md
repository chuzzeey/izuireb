# Izuire Shop Next.js project

The Next.js App Router page hosts the recovered, self-contained homepage snapshot in a full-viewport frame. Captured category, product, and account links stay on local routes. Those routes reuse the downloaded header and explain when the requested page content was not present in the homepage capture.

The source download and its backup are outside this project and are not modified.

## Run locally

```bash
npm run dev
```

Open <http://localhost:3000/>.

To create and run a production build:

```bash
npm run build
npm run start
```

Captured product data is static. Pagination, account/cart/wishlist actions, and shop links that require HOTC's backend remain unavailable or link to the live shop, as in the static reconstruction.
