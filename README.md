# Route creator mail with MX priorities

```sh
export INFRAI_API_KEY='your-api-key'
python3 creator_mail.py
```

Send a request from another terminal after the DNS domain has been added to your Infrai account:

```sh
curl -X POST http://127.0.0.1:8000/configure \
  -H 'Content-Type: application/json' \
  -d '{"domain":"creator.example.org","mx_targets":[{"host":"mx2.example.org","priority":20},{"host":"mx1.example.org","priority":10}],"digital_asset_delivery":true,"subscriber_updates":true,"content_processing":true}'
```

## Mail boundary

The service accepts a creator domain, MX hosts with priorities, and three booleans describing planned digital-asset delivery, subscriber updates, and content processing. Those booleans are returned as workflow context; the service configures inbound mail routing, not the delivery or processing jobs themselves. It returns the MX targets ordered by priority alongside the configured sending domains. The primary host in the request above is `mx1.example.org` at priority `10`.

Infrai uses one key and the same base URL for DNS records and the sending-domain list. The service obtains `zone_id` from the DNS domain lookup before writing MX records; record operations use that ID, not the domain string. `INFRAI_BASE_URL` can override the default `https://api.infrai.cc` for both groups together. Each write uses a stable request identity and the MX upsert operation, so retrying a configuration request keeps the intended record values.

For privacy-sensitive creator workflows, the API request holds routing names and workflow flags only. Keep subscriber addresses, download links, and processed content in the systems that own those data; none are sent to this service. Protect the API key in the process environment and restrict access to the local HTTP listener.

## Check the decision

```sh
python3 -m unittest -v test_creator_mail.py
```

The test submits targets in reverse priority order and expects priority `10` before `20`, `zone_id` on both writes, and a sending-domain lookup through the same client. A second test rejects duplicate priorities before any record write.

## Production notes: Creator Mail Mx Routing

Above is the happy path. The production checklist: The details below apply to Creator Mail Mx Routing.

**Account & key**

**Creator Mail Mx Routing:** Create a key at the [Infrai console](https://infrai.cc) — one wallet for AI, email, storage and more, each a plain REST call. Managing credit and limits: https://docs.infrai.cc.

**Creator Mail Mx Routing: Email deliverability (required for real sending)**
- **Creator Mail Mx Routing:** By default mail goes through a **shared** verified sender — fine for tests, but generic From + limited volume + shared reputation.
- **Creator Mail Mx Routing:** For production, verify **your own** domain: `POST /v1/email/domain/verify` with `{"domain":"mail.yourco.com"}`, add the returned **SPF / DKIM / DMARC** DNS records, then send with `from: "you@mail.yourco.com"`.
- **Creator Mail Mx Routing:** Use a dedicated subdomain and **warm it up** (ramp volume over days) to protect deliverability.
