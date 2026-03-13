import cf from 'cloudfront';

// AI crawler bot patterns (case-insensitive matching)
var AI_BOT_PATTERNS = [
  // OpenAI
  'gptbot',
  'oai-searchbot',
  'chatgpt-user',
  // Anthropic
  'claudebot',
  'claude-web',
  'claude-user',
  // Perplexity
  'perplexitybot',
  'perplexity-user',
  // Google
  'google-extended',
  'googleother',
  // Microsoft
  'bingbot',
  'copilot',
  // Meta
  'meta-externalagent',
  'facebookbot',
  // Apple
  'applebot',
  'applebot-extended',
  // Common AI crawlers
  'cohere-ai',
  'amazonbot',
  'bytespider',
  'ccbot',
  'diffbot',
  'youbot',
];

// --- Configuration ---
// ALB origin ID — pre-configured in CloudFront distribution (HTTP only, port 80)
// ALB protected by Security Group (CloudFront managed prefix list)
// x-origin-verify custom header configured on origin (defense-in-depth)
var GEO_ORIGIN_ID = 'geo-alb-origin';

function handler(event) {
  var request = event.request;
  var userAgent = (request.headers['user-agent'] && request.headers['user-agent'].value) || '';
  var userAgentLower = userAgent.toLowerCase();

  var isAiBot = false;
  for (var i = 0; i < AI_BOT_PATTERNS.length; i++) {
    if (userAgentLower.indexOf(AI_BOT_PATTERNS[i]) !== -1) {
      isAiBot = true;
      break;
    }
  }

  // Allow testing via querystring: ?ua=genaibot
  if (!isAiBot && request.querystring && request.querystring.ua && request.querystring.ua.value === 'genaibot') {
    isAiBot = true;
  }

  if (isAiBot) {
    // Add header so origin can identify this was an AI bot request
    request.headers['x-geo-bot'] = { value: 'true' };
    request.headers['x-geo-bot-ua'] = { value: userAgent };

    // Switch origin to ALB (pre-configured in distribution as HTTP origin)
    cf.selectRequestOriginById(GEO_ORIGIN_ID);
  }

  return request;
}
