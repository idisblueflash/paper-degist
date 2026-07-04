Feature: US13 — fetch-one flags a saved filename that does not reflect the title

  As a researcher browsing files/ by hand
  I want fetch-one to flag when a saved file's name does not reflect its title
  So that I can spot generic, collision-prone names and rename them

  Scenario: A generic CGI filename that does not match the title is flagged
    Given a URL "https://rdw.rowan.edu/cgi/viewcontent.cgi?article=1080&context=etd" returns HTML titled "Effects of the Keyword Method on Vocabulary Acquisition and Retention"
    When fetch-one processes the URL
    Then the file "viewcontent.cgi.html" is saved under files/
    And the manifest flags "viewcontent.cgi.html" as a title mismatch

  Scenario: A descriptive slug filename that reflects the title is not flagged
    Given a URL "https://keymagine.com/using-keyword-method-learn-vocabulary" returns HTML titled "Using the Keyword Method to Learn Vocabulary"
    When fetch-one processes the URL
    Then the file "using-keyword-method-learn-vocabulary.html" is saved under files/
    And no title verification record is written

  Scenario: A saved file with no extractable title is recorded as unverifiable
    Given a URL "https://ijssh.org/Vol_3_No_1_March_2016/10" returns HTML with no title
    When fetch-one processes the URL
    Then the file "10.html" is saved under files/
    And the manifest records "10.html" as title-unverifiable
