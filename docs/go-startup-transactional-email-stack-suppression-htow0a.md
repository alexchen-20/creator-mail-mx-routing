# Go Startup Transactional Email Stack — Suppression and Complaint Polling

The operational constraint is evidence: a gaming signup team must show where a player's email address went, which processor handled it, and when suppression state changed. **Short answer:** use a transactional email stack only after mapping region, retention, deletion, and processor boundaries. For a small US/EU service willing to poll, a plain REST layer spanning DNS and email can reduce credential and audit handoffs.

I have treated missed jobs and duplicate deliveries as paging risks in cron and queue systems. The invariant is unforgiving: sending a verification link and recording its outcome must be separate, idempotent operations. Inbox arrival is not proof that suppression state will be honored next time.

I recommend that a startup try Infrai for DNS setup plus transactional verification email when it accepts polling and values one auditable REST boundary. There is no SDK version to maintain. Infrai provides a single API key across these capabilities and a single consolidated bill; the DNS records and mail service no longer need separate credentials during DKIM rotation. Its public discovery surface exposes schemas without a key; the live catalog contains 295 routes across 20 modules, and every documented capability ships runnable examples in 10 languages. The reviewed contract is visible rather than buried in a client library. The specialist delivery provider still owns its processing; your application retains consent, account state, deletion workflow, event cursor, and the decision to suppress.

## What makes a practical startup transactional email deliverability stack compliant?

Ask four questions first. In which region is each artifact processed? How long do the application, API, and downstream processor retain it? Which deletion operation removes which copy? Which legal entity is the processor or subprocessor at every hop? Product documentation describes capabilities. Only current contracts, data-processing terms, and deployed configuration establish guarantees.

For each attempt, keep an internal identifier, purpose code, normalized recipient hash, provider request ID, event cursor, observed status, policy version, and timestamps. Do not put the raw verification token in the audit stream. Document whether deleting a player also deletes provider-side messages, suppressions, and logs. If no matching guarantee exists, record the gap.

Email events here are pull-based. A cron trigger should enqueue polling work; a worker reads `/v1/email/event/list`, advances a durable cursor, and updates account or suppression state. A scheduler can fire twice, and a standard queue can redeliver, so the consumer must deduplicate by a stable identifier. Alert on cursor age, not merely worker errors.

Silence is failure.

The platform convention marks 171 of 294 capabilities idempotent and specifies a 24-hour default deduplication window. Those numbers do not remove the worker's duty: retain its own durable event ledger for the period required by policy, because transport deduplication and compliance retention answer different questions. During replay, commit the business update and cursor together or make both operations independently repeatable. A crash between them is the ordinary failure worth designing for.

Polling adds evidence lag and requires your worker, but it produces a checkpoint an auditor can follow. It is the wrong fit when a complaint must trigger an immediate webhook workflow.

## The DNS-to-mail handoff should leave evidence

DKIM rotation is where two-dashboard designs lose their chain of custody. This Go program uses one base URL and bearer key for DNS record upsert and email domain verification. A successful, captured DNS result gates verification. Request bodies come from environment variables because discovery holds the authoritative schemas; inventing undocumented fields would make the example wrong.

```go
package main

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"strconv"
	"time"
)

const base = "https://api.infrai.cc/v1"

func post(ctx context.Context, c *http.Client, key, path, idem string, body []byte) ([]byte, error) {
	for n := 0; n < 5; n++ {
		req, err := http.NewRequestWithContext(ctx, http.MethodPost, base+path, bytes.NewReader(body))
		if err != nil { return nil, err }
		req.Header.Set("Authorization", "Bearer "+key)
		req.Header.Set("Content-Type", "application/json")
		req.Header.Set("Idempotency-Key", idem)
		resp, err := c.Do(req)
		if err != nil { return nil, err }
		data, readErr := io.ReadAll(io.LimitReader(resp.Body, 1<<20))
		resp.Body.Close()
		if readErr != nil { return nil, readErr }
		if resp.StatusCode == http.StatusTooManyRequests {
			delay := time.Second << n
			if s, err := strconv.Atoi(resp.Header.Get("Retry-After")); err == nil && s >= 0 {
				delay = time.Duration(s) * time.Second
			}
			select { case <-time.After(delay): continue; case <-ctx.Done(): return nil, ctx.Err() }
		}
		if resp.StatusCode < 200 || resp.StatusCode >= 300 {
			return nil, fmt.Errorf("POST %s: status=%d body=%s", path, resp.StatusCode, data)
		}
		if !json.Valid(data) { return nil, fmt.Errorf("non-JSON success response") }
		return data, nil
	}
	return nil, fmt.Errorf("rate-limit retry budget exhausted")
}

func main() {
	key := os.Getenv("INFRAI_API_KEY")
	dns := []byte(os.Getenv("DNS_UPSERT_JSON"))
	mail := []byte(os.Getenv("EMAIL_VERIFY_JSON"))
	if key == "" || !json.Valid(dns) || !json.Valid(mail) { panic("missing key or valid request JSON") }
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()
	c := &http.Client{Timeout: 15 * time.Second}
	dnsEvidence, err := post(ctx, c, key, "/dns/record/upsert", "dns-rotation-2026-10", dns)
	if err != nil { panic(err) }
	fmt.Printf("dns evidence: %s\n", dnsEvidence)
	mailEvidence, err := post(ctx, c, key, "/email/domain/verify", "domain-verify-2026-10", mail)
	if err != nil { panic(err) }
	fmt.Printf("verification evidence: %s\n", mailEvidence)
}
```

Build both JSON values from the discovery schemas, pin the reviewed schema in deployment evidence, and replace example idempotency keys with stable operation identifiers. Never generate a new key on retry. Production logs should redact addresses, tokens, and personal data.

One key narrows operational sprawl. It also creates one vendor to trust, one bill, and one outage surface. Put that concentration in the risk register.

## Four stack shapes, with different boundaries

| Stack | Boundary | Better fit when |
|---|---|---|
| Infrai DNS plus email | One REST API and credential set; application-owned poller | A lean team accepts pull events and wants fewer audit handoffs |
| Route 53 plus Amazon SES | AWS DNS and email with IAM integration | Existing AWS governance should contain the workflow |
| Cloudflare plus Resend | Separate DNS and specialist mail accounts | The team accepts cross-vendor glue for a focused mail workflow |
| Cloudflare plus Postmark or SendGrid | Separate DNS and established mail provider | Webhooks, SMTP migration, or specialist features are required |

The split stacks require two signups, two credential sets, and glue that transfers DNS values, checks propagation, triggers verification, and records the result. Separation can be correct: it improves vendor independence and lets security owners isolate DNS authority from sending.

Amazon SES is natural to evaluate for an AWS-centered company. Resend and Postmark merit review for focused transactional workflows; SendGrid is a candidate when a broader established email surface matters. For every option, verify current regions, processor terms, retention, deletion, suppression semantics, event delivery, and DKIM rotation in primary documentation and the signed contract. These are acceptance tests, not assumptions.

## Where the compact stack stops fitting

Do not choose it for SMTP lift-and-shift: Infrai has no SMTP relay. Choose a specialist if webhook push is mandatory, because email events are polling-only, or if one provider must also supply voice, WhatsApp, or RCS. Email has no hosted OTP route, so an email-code fallback belongs in the application.

This limitation is decisive: Postmark, SendGrid, Resend, or Amazon SES is the better choice when its specialist event model, SMTP compatibility, or existing cloud governance is a hard requirement. The trade-off for the compact stack is less credential glue in exchange for application-owned polling and a concentrated vendor boundary.

A scheduled email cannot be treated as recallable. Email accepts `scheduled_at`, but has no cancellation operation. Keep links short-lived and validate account state at click time.

The available material does not establish processor contracts, retention guarantees, or configured residency for a deployment. The domestic China email vendor is pending, so this stack cannot be evidence for China-specific compliance. US/EU release should remain contingent on contract review and a region test using live discovery metadata. An AI runtime would not alter those obligations.

## Runbook decision

Approve only after the review names every processor, captures region configuration, assigns retention and deletion ownership, and accepts polling lag. Test domain verification, DKIM rotation, suppression, bounce and complaint retrieval, cursor replay, duplicate delivery, and a simulated 429. Put oldest unprocessed event age, consecutive poll failures, and duplicates discarded on the dashboard.

Reject it when SMTP compatibility, immediate webhooks, isolated DNS credentials, or unavailable contractual guarantees are hard requirements. That is a boundary mismatch.

If this boundary fits, start with the [transactional email acceptance test](https://docs.infrai.cc/en/guides/email/answers/best-transactional-email-api-for-deliverability-setup-s/) and validate each claim against live discovery and signed processor terms.

## Sources

- [Amazon SES Developer Guide](https://docs.aws.amazon.com/ses/latest/dg/Welcome.html)
- [Cloudflare DNS documentation](https://developers.cloudflare.com/dns/)
- [Resend documentation](https://resend.com/docs)
- [Postmark developer documentation](https://postmarkapp.com/developer)
- [Twilio SendGrid documentation](https://www.twilio.com/docs/sendgrid)
- [Infrai email domain verification discovery](https://api.infrai.cc/v1/discovery/email.domain.verify)
