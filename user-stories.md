

# User Stories

## US 1 Fetching the paper file

As a *researcher*, i want to *fetch the paper*, so that i can *handle it* later.

### Acceptence Critieria

1. Given a text with URLs
   - when parse-url process the text
     - then we got a list of URLs
2. Given a list of URLs
   - when fetch-list process the list
     - then we got the file of each URL
3. Given one URL
   - when fetch-one process the URL
     - then we fetch the file
     - and save it under files/ folder

## US 2 Converting PDF

As a *researcher*, i want to *convert PDF paper into text file*, so that i can *process it with LLM* later.

## US 3 Formatting Paper

As a *researcher*, i want to *convert text file into MD file*, so that i can *process it with LLM* later.

## US 4 Importing Paper

As a *researcher*, i want to *import MD files into src/* folder of LLM wiki, so that *my skill* *can compile them*.

## US 5 Compiling Paper

As a *Karpathy-wiki Skill*, i want to *compile the new files under src/*, so that i can *extract concepts*.

## US 6 Rating Paper

As a *Karpathy-wiki Skill*, i want to *rate each paper's depth need (skim / study / reimplement)*, so that *I don't flatten every topic into the same report*.

