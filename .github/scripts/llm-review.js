/**
 * LLM Code Review Script
 * 
 * Fetches PR diff, sends to LLM for review, and posts comment on PR.
 * 
 * Required environment variables:
 * - GITHUB_TOKEN: GitHub token with PR read/write permissions
 * - LLM_API_KEY: API key for LLM provider
 * - LLM_BASE_URL: Base URL for LLM API (OpenAI-compatible)
 * - LLM_MODEL: Model to use for review
 * - GITHUB_REPOSITORY: owner/repo format
 * - PR_NUMBER: Pull request number
 */

const SYSTEM_PROMPT = `You are a senior code reviewer. Analyze the provided git diff and provide a concise, actionable code review.

Focus on:
- Potential bugs or security issues
- Performance concerns
- Code quality and best practices
- Missing error handling
- Suggestions for improvement

Format your review in Markdown with sections:
## 🔍 Summary
Brief overview of changes

## ⚠️ Issues Found
List of problems (if any)

## 💡 Suggestions
Improvement recommendations

## ✅ What's Good
Positive aspects of the code

Be constructive and specific. If the code looks good, say so briefly.`;

async function fetchDiff(owner, repo, prNumber, token) {
  const response = await fetch(
    `https://api.github.com/repos/${owner}/${repo}/pulls/${prNumber}`,
    {
      headers: {
        Authorization: `Bearer ${token}`,
        Accept: 'application/vnd.github.v3.diff',
        'X-GitHub-Api-Version': '2022-11-28'
      }
    }
  );
  
  if (!response.ok) {
    throw new Error(`Failed to fetch diff: ${response.status} ${response.statusText}`);
  }
  
  return response.text();
}

async function fetchPRInfo(owner, repo, prNumber, token) {
  const response = await fetch(
    `https://api.github.com/repos/${owner}/${repo}/pulls/${prNumber}`,
    {
      headers: {
        Authorization: `Bearer ${token}`,
        Accept: 'application/vnd.github.v3+json',
        'X-GitHub-Api-Version': '2022-11-28'
      }
    }
  );
  
  if (!response.ok) {
    throw new Error(`Failed to fetch PR info: ${response.status} ${response.statusText}`);
  }
  
  return response.json();
}

async function callLLM(diff, prTitle, prBody, baseUrl, apiKey, model) {
  const userPrompt = `Review the following Pull Request:

**Title:** ${prTitle}
**Description:** ${prBody || 'No description provided'}

**Diff:**
\`\`\`diff
${diff.slice(0, 50000)}
\`\`\`

${diff.length > 50000 ? '\n(Diff truncated due to size)' : ''}`;

  const response = await fetch(`${baseUrl}/chat/completions`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${apiKey}`
    },
    body: JSON.stringify({
      model: model,
      messages: [
        { role: 'system', content: SYSTEM_PROMPT },
        { role: 'user', content: userPrompt }
      ],
      temperature: 0.3,
      max_tokens: 2000
    })
  });

  if (!response.ok) {
    const error = await response.text();
    throw new Error(`LLM API error: ${response.status} - ${error}`);
  }

  const data = await response.json();
  return data.choices[0].message.content;
}

async function postComment(owner, repo, prNumber, body, token) {
  const response = await fetch(
    `https://api.github.com/repos/${owner}/${repo}/issues/${prNumber}/comments`,
    {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${token}`,
        Accept: 'application/vnd.github.v3+json',
        'X-GitHub-Api-Version': '2022-11-28',
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        body: `## 🤖 AI Code Review\n\n${body}\n\n---\n*This review was generated automatically by LLM.*`
      })
    }
  );

  if (!response.ok) {
    const error = await response.text();
    throw new Error(`Failed to post comment: ${response.status} - ${error}`);
  }

  return response.json();
}

async function main() {
  // Get env variables
  const token = process.env.GITHUB_TOKEN;
  const llmApiKey = process.env.LLM_API_KEY;
  const llmBaseUrl = process.env.LLM_BASE_URL || 'https://api.openai.com/v1';
  const llmModel = process.env.LLM_MODEL || 'gpt-4o-mini';
  const repository = process.env.GITHUB_REPOSITORY;
  const prNumber = process.env.PR_NUMBER;

  if (!token || !llmApiKey || !repository || !prNumber) {
    console.error('Missing required environment variables');
    console.error('Required: GITHUB_TOKEN, LLM_API_KEY, GITHUB_REPOSITORY, PR_NUMBER');
    process.exit(1);
  }

  const [owner, repo] = repository.split('/');

  console.log(`Reviewing PR #${prNumber} in ${repository}...`);

  try {
    // Fetch PR info and diff
    console.log('Fetching PR info and diff...');
    const [prInfo, diff] = await Promise.all([
      fetchPRInfo(owner, repo, prNumber, token),
      fetchDiff(owner, repo, prNumber, token)
    ]);

    if (!diff || diff.trim().length === 0) {
      console.log('No changes in PR, skipping review');
      return;
    }

    console.log(`Diff size: ${diff.length} characters`);

    // Call LLM for review
    console.log('Calling LLM for review...');
    const review = await callLLM(
      diff,
      prInfo.title,
      prInfo.body,
      llmBaseUrl,
      llmApiKey,
      llmModel
    );

    console.log('Review received, posting comment...');

    // Post comment
    await postComment(owner, repo, prNumber, review, token);

    console.log('✅ Review posted successfully!');
  } catch (error) {
    console.error('❌ Error:', error.message);
    process.exit(1);
  }
}

main();
