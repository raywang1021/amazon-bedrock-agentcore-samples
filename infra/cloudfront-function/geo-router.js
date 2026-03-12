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
// Replace with your API Gateway domain for GEO content
var GEO_ORIGIN_DOMAIN = 'h77cl56kzg.execute-api.us-east-1.amazonaws.com';
var GEO_ORIGIN_PATH = '/prod';

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

    // Switch origin to API Gateway that serves GEO content from DynamoDB
    cf.updateRequestOrigin({
      domainName: GEO_ORIGIN_DOMAIN,
      originPath: GEO_ORIGIN_PATH,
      originAccessControlConfig: {
        enabled: false,
      },
    });
  }

  return request;
}
